"""Text preparation and speech synthesis.

The engine is Kokoro (Apache 2.0, 82M parameters), which runs on a CPU or GPU
with no per-use fee and no service to subscribe to. That matters for NLS: the
SOW requires software the Library owns outright, with no recurring licenses.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 24_000
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


@dataclass
class Lexicon:
    """Pronunciation fixes as ordered regex substitutions. Every hit is logged for QA."""

    rules: list[tuple[re.Pattern, str]]

    @classmethod
    def load(cls, path: str | Path) -> "Lexicon":
        data = json.loads(Path(path).read_text())
        return cls([(re.compile(r["pattern"]), r["say"]) for r in data["rules"]])

    def apply(self, text: str, log: list | None = None) -> str:
        for pattern, say in self.rules:
            def sub(m: re.Match) -> str:
                if log is not None:
                    log.append({"text": m.group(0), "said": m.expand(say)})
                return m.expand(say)

            text = pattern.sub(sub, text)
        return text


def speakable_heading(heading: str) -> str:
    """'Article IV' -> 'Article 4'; 'Section 2' stays. Spoken headings avoid roman numerals."""
    m = re.fullmatch(r"(?i)(article|amendment|part|chapter)\s+([IVX]+)", heading.strip())
    if m and m.group(2).upper() in ROMAN:
        return f"{m.group(1).title()} {ROMAN[m.group(2).upper()]}"
    return heading


def sentences(paragraph: str) -> list[str]:
    """Paragraph into sentence-sized phrases so each SMIL clip stays short and seekable."""
    parts = re.split(r"(?<=[.;:!?])\s+(?=[A-Z\"'(\[])", paragraph.strip())
    out: list[str] = []
    for part in parts:
        if out and len(out[-1]) < 40:
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return [p for p in out if p]


class Kokoro:
    name = "Kokoro-82M (Apache 2.0)"

    def __init__(self, voice: str = "af_heart", speed: float = 0.95):
        from kokoro import KPipeline  # imported here so tests run without the model

        self.voice = voice
        self.speed = speed
        self.pipeline = KPipeline(lang_code=voice[0])

    def __call__(self, text: str) -> np.ndarray:
        chunks = [np.asarray(audio, dtype=np.float32) for _, _, audio in self.pipeline(text, voice=self.voice, speed=self.speed)]
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
