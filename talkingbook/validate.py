"""Checks a built DTB against ANSI/NISO Z39.86-2005 DTDs and NLS Spec 1203 rules.

Every check reports pass or fail with detail. Clip timing is measured from the
master WAVs, independently of the numbers the builder wrote.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/", "smil": "http://www.w3.org/2001/SMIL20/", "opf": "http://openebook.org/namespaces/oeb-package/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
# Classes used here, all from NLS Spec 1203 Appendix A, Table 1.
CLASSES = {"title/author", "prelimitem", "chapter", "section", "subsection", "part", "close", "introduction", "preface", "foreword"}


def seconds(clock: str) -> float:
    h, m, s = clock.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})

    @property
    def passed(self) -> bool:
        return all(c["ok"] for c in self.checks)


def speech_edges(samples: np.ndarray, rate: int, begin: float, end: float, threshold: float) -> tuple[float | None, float | None]:
    """First and last 5 ms frame above threshold inside [begin, end]."""
    a, b = int(begin * rate), int(end * rate)
    seg = samples[a:b]
    n = int(rate * 0.005)
    frames = len(seg) // n
    if frames == 0:
        return None, None
    rms = np.sqrt(np.mean(seg[: frames * n].reshape(frames, n) ** 2, axis=1))
    loud = np.nonzero(rms > threshold)[0]
    if len(loud) == 0:
        return None, None
    return begin + loud[0] * n / rate, begin + (loud[-1] + 1) * n / rate


def validate(out: Path, pid: str) -> Report:
    import soundfile as sf

    r = Report()
    d = out / "dtb"
    files = sorted(p.name for p in d.iterdir() if p.is_file())

    # Files and names (Spec 1203 §3.1)
    r.add("File names are lower case", all(f == f.lower() for f in files), ", ".join(f for f in files if f != f.lower()))
    r.add("No more than 250 files", len(files) <= 250, f"{len(files)} files")
    audio = sorted(f for f in files if re.fullmatch(rf"{pid}-\d{{4}}\.mp3", f))
    expected = [f"{pid}-{i:04d}.mp3" for i in range(1, len(audio) + 1)]
    r.add("Audio sequence starts at -0001 and is continuous", audio == expected, f"{len(audio)} primary audio files")
    for name in (f"{pid}.opf", f"{pid}.ncx", f"{pid}.smil", f"{pid}hdgs.mp3", f"{pid}dtb.md5"):
        r.add(f"{name} present", name in files)

    # DTD validation with xmllint, offline, against the DTDs bundled in the book (§3.10.3).
    # The OEB package DTD names its entity file by URL; a catalog maps that URL to the bundled copy.
    catalog = out / "catalog.xml"
    catalog.write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f'  <system systemId="http://openebook.org/dtds/oeb-1.2/oeb12.ent" uri="{(d / "oeb12.ent").as_uri()}"/>\n'
        f'  <public publicId="+//ISBN 0-9673008-1-9//DTD OEB 1.2 Entities//EN" uri="{(d / "oeb12.ent").as_uri()}"/>\n'
        "</catalog>\n"
    )
    # XML_CATALOG_FILES is space-separated, so pass a URI in case the path has spaces.
    env = {**os.environ, "XML_CATALOG_FILES": catalog.as_uri()}
    for name in (f"{pid}.opf", f"{pid}.ncx", f"{pid}.smil", f"{pid}dtb.md5"):
        res = subprocess.run(["xmllint", "--noout", "--valid", "--nonet", name], cwd=d, capture_output=True, text=True, env=env)
        clean = res.returncode == 0 and not res.stderr.strip()
        r.add(f"{name} is valid to its DTD (offline)", clean, res.stderr.strip()[:300])

    ncx = ET.parse(d / f"{pid}.ncx").getroot()
    smil = ET.parse(d / f"{pid}.smil").getroot()
    opf = ET.parse(d / f"{pid}.opf").getroot()

    # NCX (§3.4)
    points = ncx.findall(".//ncx:navPoint", NS)
    orders = [int(p.get("playOrder")) for p in points]
    r.add("navPoint playOrder runs 1..n in document order", orders == list(range(1, len(points) + 1)), f"{len(points)} navPoints")
    r.add("No more than 5,000 navPoints", len(points) <= 5000)
    bad_class = [p.get("class") for p in points if p.get("class") not in CLASSES]
    r.add("navPoint classes come from Spec 1203 Table 1", not bad_class, ", ".join(sorted(set(bad_class))))
    smil_ids = {el.get("id") for el in smil.iter() if el.get("id")}
    targets = [p.find("ncx:content", NS).get("src").split("#")[1] for p in points]
    r.add("Every navPoint points to a SMIL element", all(t in smil_ids for t in targets))
    labels_ok = all(p.find("ncx:navLabel/ncx:text", NS) is not None and p.find("ncx:navLabel/ncx:audio", NS) is not None for p in points)
    r.add("Every navLabel has text and audio", labels_ok)

    def depth(el, level=0) -> int:
        kids = el.findall("ncx:navPoint", NS)
        return max((depth(k, level + 1) for k in kids), default=level)

    declared = int(ncx.find("ncx:head/ncx:meta[@name='dtb:depth']", NS).get("content"))
    r.add("dtb:depth matches the navPoint nesting", declared == depth(ncx.find("ncx:navMap", NS)), f"declared {declared}")

    # SMIL (§3.3)
    audios = smil.findall(".//smil:audio", NS)
    clips_ok = all(seconds(a.get("clipBegin")) < seconds(a.get("clipEnd")) for a in audios)
    r.add("Every SMIL audio has clipBegin before clipEnd", clips_ok, f"{len(audios)} clips")
    r.add("SMIL file is at most 100 KiB", (d / f"{pid}.smil").stat().st_size <= 100 * 1024, f"{(d / f'{pid}.smil').stat().st_size / 1024:.1f} KiB")
    r.add("Every audio src exists", all(a.get("src") in files for a in audios + ncx.findall(".//ncx:audio", NS)))

    # OPF (§3.5, §5.3)
    uid = opf.find(".//dc:Identifier", NS)
    smil_uid = smil.find("smil:head/smil:meta[@name='dtb:uid']", NS).get("content")
    ncx_uid = ncx.find("ncx:head/ncx:meta[@name='dtb:uid']", NS).get("content")
    r.add("dc:Identifier has id=uid and matches NCX and SMIL", uid is not None and uid.get("id") == "uid" and uid.text == smil_uid == ncx_uid, uid.text if uid is not None else "missing")
    meta = {m.get("name"): m.get("content") for m in opf.findall(".//opf:meta", NS)}
    r.add("dtb:multimediaType is audioNCX", meta.get("dtb:multimediaType") == "audioNCX")
    total = sum(seconds(a.get("clipEnd")) - seconds(a.get("clipBegin")) for a in audios)
    r.add("dtb:totalTime equals the summed SMIL audio within 1 s", abs(seconds(meta.get("dtb:totalTime", "0:0:0")) - total) <= 1.0, f"{meta.get('dtb:totalTime')} vs {total:.1f} s")
    manifest = {i.get("href") for i in opf.findall(".//opf:item", NS)}
    r.add("Manifest lists every file except the checksum file", manifest == set(files) - {f"{pid}dtb.md5"}, ", ".join(sorted(set(files) - manifest - {f'{pid}dtb.md5'})))
    r.add("dc:Date is yyyy-mm", bool(re.fullmatch(r"\d{4}-\d{2}", opf.find(".//dc:Date", NS).text or "")))

    # Checksums (§3.9)
    check = ET.parse(d / f"{pid}dtb.md5").getroot()
    listed = {f.findtext("filename"): f.findtext("checksum") for f in check.findall("file")}
    actual = {f: hashlib.md5((d / f).read_bytes()).hexdigest() for f in files if f != f"{pid}dtb.md5"}
    r.add("Checksum file matches every file", listed == actual, f"{len(listed)} files")
    r.add("Checksum <book> matches the dc:Identifier", check.findtext("book") == (uid.text if uid is not None else None))

    # Clip timing measured from the masters (§3.3.4.2): narration starts 80-120 ms after clipBegin
    # and ends 150-300 ms before clipEnd.
    misses, measured = [], 0
    for name in audio + [f"{pid}hdgs.mp3"]:
        wav = out / "masters" / name.replace(".mp3", ".wav")
        samples, rate = sf.read(wav, dtype="float32")
        threshold = float(np.max(np.abs(samples))) * 10 ** (-40 / 20)
        clips = [a for a in audios + ncx.findall(".//ncx:audio", NS) if a.get("src") == name]
        for a in clips:
            begin, end = seconds(a.get("clipBegin")), seconds(a.get("clipEnd"))
            on, off = speech_edges(samples, rate, begin, end, threshold)
            measured += 1
            if on is None or not (0.075 <= on - begin <= 0.125 and 0.145 <= end - off <= 0.305):
                misses.append(f"{name} {a.get('clipBegin')}")
    r.add("Clip timing within Spec 1203 windows (measured)", not misses, f"{measured - len(misses)}/{measured} clips" + (f"; first miss {misses[0]}" if misses else ""))

    # Encoded audio keeps the master's length
    drift = []
    for name in audio + [f"{pid}hdgs.mp3"]:
        mp3 = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(d / name)], capture_output=True, text=True).stdout or 0)
        wav = sf.info(out / "masters" / name.replace(".mp3", ".wav")).duration
        drift.append(abs(mp3 - wav))
    r.add("MP3 duration within 0.1 s of its master", max(drift) <= 0.1, f"max drift {max(drift):.3f} s")
    return r
