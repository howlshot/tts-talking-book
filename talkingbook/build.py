"""The pipeline: source text -> speech -> master WAVs -> MP3 -> OPF, NCX, SMIL, checksums."""
from __future__ import annotations

import json
import shutil
import time
from datetime import date
from pathlib import Path

import numpy as np

from . import dtb
from .audio import Clip, Track, encode_mp3, normalize, trim, write_wav
from .source import Division, build_divisions, read_epub
from .speech import SAMPLE_RATE, Lexicon, sentences, speakable_heading

DTD_DIR = Path(__file__).parent / "dtd"

# Silence around each phrase, in seconds (lead, tail). Clip marks sit 0.1 s
# before and 0.2 s after the speech, so every pad leaves them inside silence.
HEADING = (0.60, 0.90)
SENTENCE = (0.25, 0.40)
PARAGRAPH_END = (0.25, 0.75)


class Builder:
    def __init__(self, config: dict, root: Path, out: Path, engine, voice: str):
        self.c = config
        self.root = root
        self.out = out
        self.engine = engine
        self.voice = voice
        self.lexicon = Lexicon.load(root / config["lexicon"]) if config.get("lexicon") else Lexicon([])
        self.lexicon_hits: list[dict] = []
        self.pars: list[dtb.Par] = []
        self.synth_seconds = 0.0
        self.phrases = 0

    def speak(self, text: str) -> np.ndarray:
        said = self.lexicon.apply(text, self.lexicon_hits)
        self.last_said = said
        t0 = time.monotonic()
        audio = trim(self.engine(said), SAMPLE_RATE)
        self.synth_seconds += time.monotonic() - t0
        self.phrases += 1
        if len(audio) == 0:
            raise RuntimeError(f"Synthesis returned silence for: {text[:80]!r}")
        return audio

    def par(self, track: Track, audio_file: str, text: str, pads: tuple[float, float], cls: str | None = None) -> str:
        clip = track.add(self.speak(text), *pads)
        pid = f"par{len(self.pars) + 1}"
        self.pars.append(dtb.Par(pid, audio_file, clip, cls, self.last_said))
        return pid

    def narrate(self, d: Division, track: Track, audio_file: str, headings: Track) -> dtb.Nav:
        spoken = speakable_heading(d.heading)
        target = self.par(track, audio_file, f"{spoken}.", HEADING, d.cls)
        nav = dtb.Nav(d.heading.title() if d.heading.isupper() else d.heading, d.cls, target, headings.add(self.speak(f"{spoken}."), *HEADING))
        for paragraph in d.paragraphs:
            parts = sentences(paragraph)
            for i, s in enumerate(parts):
                self.par(track, audio_file, s, PARAGRAPH_END if i == len(parts) - 1 else SENTENCE)
        for child in d.children:
            nav.children.append(self.narrate(child, track, audio_file, headings))
        return nav

    def run(self) -> dict:
        c, pid = self.c, self.c["pid"]
        started = time.monotonic()
        blocks = read_epub(self.root / c["source"], c.get("start"), c.get("stop"))
        source_title, divisions = build_divisions(blocks, c.get("preliminary_heading", "Preamble"))
        title = c.get("title") or source_title

        dtb_dir, masters = self.out / "dtb", self.out / "masters"
        for d in (dtb_dir, masters):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)

        headings = Track(SAMPLE_RATE)
        title_clip = headings.add(self.speak(f"{title}."), *HEADING)
        author_clip = headings.add(self.speak(f"{c['author_phrase']} {c['spoken_author']}."), *HEADING)

        # Track 1 opens with the title/author announcement and holds the front
        # matter; each chapter gets its own track; the closing announcement
        # ends the last one. Sequence numbers follow Spec 1203 §3.1.2.1.
        groups: list[list[Division]] = [[d for d in divisions if d.cls == "prelimitem"]]
        groups += [[d] for d in divisions if d.cls != "prelimitem"]
        tracks: list[Track] = []
        files: list[str] = []
        nav: list[dtb.Nav] = []
        for n, group in enumerate(groups, start=1):
            track, name = Track(SAMPLE_RATE), f"{pid}-{n:04d}.mp3"
            if n == 1:
                opening = f"{title}. {c['author_phrase']} {c['spoken_author']}. Read by a synthetic voice."
                target = self.par(track, name, opening, HEADING, "title/author")
                nav.append(dtb.Nav(title, "title/author", target, title_clip))
            for d in group:
                nav.append(self.narrate(d, track, name, headings))
            if n == len(groups):
                target = self.par(track, name, f"End of {title}.", HEADING, "close")
                nav.append(dtb.Nav(f"End of {title}", "close", target, headings.add(self.speak(f"End of {title}."), *HEADING)))
            tracks.append(track)
            files.append(name)

        loudness = {}
        for track, name in list(zip(tracks, files)) + [(headings, f"{pid}hdgs.mp3")]:
            wav = masters / name.replace(".mp3", ".wav")
            write_wav(wav, track.samples(), SAMPLE_RATE)
            loudness[wav.name] = normalize(wav)
            encode_mp3(wav, dtb_dir / name)

        today = date.today().isoformat()
        plan = dtb.Plan(
            pid=pid, uid=c["uid"], title=title, author=c["author"], author_phrase=c["author_phrase"],
            language="en", narrator=f"Kokoro {self.voice} (synthetic voice)", producer="Studio Chingie LLC", produced=today,
            source_date=c.get("source_date", ""), pars=self.pars, nav=nav, title_clip=title_clip, author_clip=author_clip,
            audio_files=files, description=c.get("description", ""), subject=c.get("subject", ""),
        )
        for dtd in dtb.DTDS:
            shutil.copy(DTD_DIR / dtd, dtb_dir / dtd)
        (dtb_dir / f"{pid}.smil").write_text(dtb.smil(plan))
        (dtb_dir / f"{pid}.ncx").write_text(dtb.ncx(plan))
        (dtb_dir / f"{pid}.opf").write_text(dtb.opf(plan))
        (dtb_dir / f"{pid}dtb.md5").write_text(dtb.checksum_file(plan, dtb_dir))

        audio_seconds = sum(t.seconds for t in tracks)
        report = {
            "title": title,
            "pid": pid,
            "engine": getattr(self.engine, "name", type(self.engine).__name__),
            "voice": self.voice,
            "built": today,
            "phrases": self.phrases,
            "smil_pars": len(self.pars),
            "nav_points": sum(1 for _ in _walk(nav)),
            "audio_seconds": round(audio_seconds, 1),
            "total_time": dtb.clock(plan.total_time),
            "synthesis_seconds": round(self.synth_seconds, 1),
            "realtime_factor": round(audio_seconds / self.synth_seconds, 1) if self.synth_seconds else None,
            "build_seconds": round(time.monotonic() - started, 1),
            "loudness": {k: {"integrated_lufs": float(v["input_i"]), "true_peak_dbtp": float(v["input_tp"])} for k, v in loudness.items()},
            "lexicon_hits": self.lexicon_hits,
            "files": sorted(p.name for p in dtb_dir.iterdir()),
        }
        (self.out / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
        (self.out / "plan.json").write_text(json.dumps(_plan_json(plan), indent=2) + "\n")
        return report


def _walk(nav: list[dtb.Nav]):
    for n in nav:
        yield n
        yield from _walk(n.children)


def _plan_json(plan: dtb.Plan) -> dict:
    """Speech positions for the validator and the inspector page."""
    def navj(n: dtb.Nav) -> dict:
        return {"label": n.label, "cls": n.cls, "target": n.target, "heading": [n.heading_clip.begin, n.heading_clip.end], "children": [navj(c) for c in n.children]}

    return {
        "pid": plan.pid,
        "title": plan.title,
        "pars": [{"id": p.id, "audio": p.audio, "speech": [round(p.clip.speech_start, 3), round(p.clip.speech_end, 3)], "clip": [p.clip.begin, p.clip.end], "cls": p.cls, "said": p.said} for p in plan.pars],
        "nav": [navj(n) for n in plan.nav],
        "title_clip": [plan.title_clip.begin, plan.title_clip.end],
        "author_clip": [plan.author_clip.begin, plan.author_clip.end],
    }
