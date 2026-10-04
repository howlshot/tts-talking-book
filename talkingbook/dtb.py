"""Writers for the DTB file set: package (OPF), navigation (NCX), synchronization
(SMIL) and the NLS checksum file. File names follow NLS Spec 1203 §3.1.2."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .audio import Clip

GENERATOR = "Studio Chingie TTS Talking Book 0.1"
DTDS = ["ncx-2005-1.dtd", "dtbsmil-2005-1.dtd", "oebpkg12.dtd", "oeb12.ent"]


def clock(seconds: float) -> str:
    """SMIL full clock value, e.g. 0:01:02.345."""
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms:03d}"


@dataclass
class Par:
    id: str
    audio: str
    clip: Clip
    cls: str | None = None
    said: str = ""  # text as sent to the voice, after the lexicon


@dataclass
class Nav:
    label: str
    cls: str
    target: str  # par id of the spoken heading in the primary audio
    heading_clip: Clip  # the same words in the headings file
    children: list["Nav"] = field(default_factory=list)


@dataclass
class Plan:
    pid: str  # production identifier; lowercase
    uid: str
    title: str
    author: str
    author_phrase: str
    language: str
    narrator: str
    producer: str
    produced: str  # yyyy-mm-dd
    source_date: str
    pars: list[Par]
    nav: list[Nav]
    title_clip: Clip
    author_clip: Clip
    audio_files: list[str]
    description: str = ""
    subject: str = ""

    @property
    def smil(self) -> str:
        return f"{self.pid}.smil"

    @property
    def headings(self) -> str:
        return f"{self.pid}hdgs.mp3"

    @property
    def total_time(self) -> float:
        return sum(p.clip.end - p.clip.begin for p in self.pars)

    def depth(self) -> int:
        def d(items: list[Nav]) -> int:
            return max((1 + d(n.children) for n in items), default=0)
        return d(self.nav)


def audio_el(src: str, clip: Clip, indent: str) -> str:
    return f'{indent}<audio src="{src}" clipBegin="{clock(clip.begin)}" clipEnd="{clock(clip.end)}"/>'


def smil(plan: Plan) -> str:
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE smil PUBLIC "-//NISO//DTD dtbsmil 2005-1//EN" "dtbsmil-2005-1.dtd">',
        '<smil xmlns="http://www.w3.org/2001/SMIL20/">',
        "  <head>",
        f'    <meta name="dtb:uid" content={quoteattr(plan.uid)}/>',
        f'    <meta name="dtb:generator" content="{GENERATOR}"/>',
        '    <meta name="dtb:totalElapsedTime" content="0:00:00.000"/>',
        "  </head>",
        "  <body>",
        f'    <seq id="mseq" dur="{clock(plan.total_time)}">',
    ]
    for p in plan.pars:
        cls = f" class={quoteattr(p.cls)}" if p.cls else ""
        rows += [f'      <par id="{p.id}"{cls}>', audio_el(p.audio, p.clip, "        "), "      </par>"]
    rows += ["    </seq>", "  </body>", "</smil>", ""]
    return "\n".join(rows)


def ncx(plan: Plan) -> str:
    counter = [0]

    def point(n: Nav, indent: str) -> list[str]:
        counter[0] += 1
        out = [
            f'{indent}<navPoint id="nav{counter[0]}" class={quoteattr(n.cls)} playOrder="{counter[0]}">',
            f"{indent}  <navLabel>",
            f"{indent}    <text>{escape(n.label)}</text>",
            audio_el(plan.headings, n.heading_clip, f"{indent}    "),
            f"{indent}  </navLabel>",
            f'{indent}  <content src="{plan.smil}#{n.target}"/>',
        ]
        for child in n.children:
            out += point(child, indent + "  ")
        return out + [f"{indent}</navPoint>"]

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "ncx-2005-1.dtd">',
        f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{plan.language}">',
        "  <head>",
        f'    <meta name="dtb:uid" content={quoteattr(plan.uid)}/>',
        f'    <meta name="dtb:depth" content="{plan.depth()}"/>',
        f'    <meta name="dtb:generator" content="{GENERATOR}"/>',
        '    <meta name="dtb:totalPageCount" content="0"/>',
        '    <meta name="dtb:maxPageNumber" content="0"/>',
        "  </head>",
        "  <docTitle>",
        f"    <text>{escape(plan.title)}</text>",
        audio_el(plan.headings, plan.title_clip, "    "),
        "  </docTitle>",
        "  <docAuthor>",
        f"    <text>{escape(plan.author_phrase)} {escape(plan.author)}</text>",
        audio_el(plan.headings, plan.author_clip, "    "),
        "  </docAuthor>",
        "  <navMap>",
    ]
    for n in plan.nav:
        rows += point(n, "    ")
    rows += ["  </navMap>", "</ncx>", ""]
    return "\n".join(rows)


def opf(plan: Plan) -> str:
    def dc(name: str, value: str, attrs: str = "") -> str:
        return f"      <dc:{name}{attrs}>{escape(value)}</dc:{name}>"

    def meta(name: str, value: str) -> str:
        return f'      <meta name="{name}" content={quoteattr(value)}/>'

    items = [("opf", f"{plan.pid}.opf", "text/xml"), ("ncx", f"{plan.pid}.ncx", "application/x-dtbncx+xml"), ("smil", plan.smil, "application/smil")]
    items += [(f"audio{i + 1}", name, "audio/mpeg") for i, name in enumerate(plan.audio_files)]
    items += [("hdgs", plan.headings, "audio/mpeg")]
    items += [(f"dtd{i + 1}", name, "application/xml-dtd") for i, name in enumerate(DTDS)]
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE package PUBLIC "+//ISBN 0-9673008-1-9//DTD OEB 1.2 Package//EN" "oebpkg12.dtd">',
        '<package xmlns="http://openebook.org/namespaces/oeb-package/1.0/" unique-identifier="uid">',
        "  <metadata>",
        '    <dc-metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oebpackage="http://openebook.org/namespaces/oeb-package/1.0/">',
        dc("Title", plan.title),
        dc("Creator", plan.author),
        dc("Subject", plan.subject or "Sample"),
        dc("Description", plan.description),
        dc("Publisher", plan.producer),
        dc("Date", plan.produced[:7]),
        dc("Format", "ANSI/NISO Z39.86-2005"),
        dc("Identifier", plan.uid, ' id="uid" scheme="DTB"'),
        dc("Language", plan.language),
        dc("Rights", "Public domain text; synthetic narration."),
        "    </dc-metadata>",
        "    <x-metadata>",
        meta("dtb:sourceDate", plan.source_date),
        meta("dtb:multimediaType", "audioNCX"),
        meta("dtb:multimediaContent", "audio"),
        meta("dtb:narrator", plan.narrator),
        meta("dtb:producer", plan.producer),
        meta("dtb:producedDate", plan.produced),
        meta("dtb:revision", "0"),
        meta("dtb:revisionDate", plan.produced),
        meta("dtb:totalTime", clock(plan.total_time)),
        meta("dtb:audioFormat", "MP3"),
        "    </x-metadata>",
        "  </metadata>",
        "  <manifest>",
    ]
    rows += [f'    <item id="{i}" href="{h}" media-type="{t}"/>' for i, h, t in items]
    rows += ["  </manifest>", "  <spine>", '    <itemref idref="smil"/>', "  </spine>", "</package>", ""]
    return "\n".join(rows)


def checksum_file(plan: Plan, folder: Path) -> str:
    """NLS Spec 1203 §3.9: MD5 of every file except the checksum file itself."""
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE diskcheck [",
        "<!ELEMENT diskcheck (book, file+)>",
        '<!ATTLIST diskcheck version CDATA #FIXED "1.0">',
        "<!ELEMENT book (#PCDATA)>",
        "<!ELEMENT file (filename, checksum)>",
        "<!ATTLIST file type CDATA #IMPLIED content CDATA #IMPLIED>",
        "<!ELEMENT filename (#PCDATA)>",
        "<!ELEMENT checksum (#PCDATA)>",
        "<!ATTLIST checksum type CDATA #REQUIRED>",
        "]>",
        '<diskcheck version="1.0">',
        f"  <book>{escape(plan.uid)}</book>",
    ]
    for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith("dtb.md5")):
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        rows.append(f'  <file><filename>{escape(path.name)}</filename><checksum type="MD5">{digest}</checksum></file>')
    rows += ["</diskcheck>", ""]
    return "\n".join(rows)
