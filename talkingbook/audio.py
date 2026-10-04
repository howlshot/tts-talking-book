"""Narration into master tracks, with clip times placed by NLS Spec 1203 §3.3.4.2.

Each clip begins 80-120 ms before its narration and ends 150-300 ms after it,
inside the silence between phrases. The builder trims each synthesized phrase
to its speech, pads it with silence it controls, and records where the speech
sits, so the timing rule holds by construction. validate.py then measures the
finished WAV masters independently.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CLIP_LEAD = 0.100  # clipBegin this far before narration (rule: 0.080-0.120 s)
CLIP_TAIL = 0.200  # clipEnd this far after narration (rule: 0.150-0.300 s)


def trim(samples: np.ndarray, rate: int, threshold: float = 0.01, frame: float = 0.010) -> np.ndarray:
    """Cut leading and trailing silence, judged on 10 ms RMS frames."""
    n = max(1, int(rate * frame))
    if len(samples) < n:
        return samples
    frames = len(samples) // n
    rms = np.sqrt(np.mean(samples[: frames * n].reshape(frames, n) ** 2, axis=1))
    loud = np.nonzero(rms > threshold)[0]
    if len(loud) == 0:
        return samples[:0]
    return samples[loud[0] * n : (loud[-1] + 1) * n]


@dataclass
class Clip:
    speech_start: float
    speech_end: float

    @property
    def begin(self) -> float:
        return round(self.speech_start - CLIP_LEAD, 3)

    @property
    def end(self) -> float:
        return round(self.speech_end + CLIP_TAIL, 3)


@dataclass
class Track:
    rate: int
    parts: list[np.ndarray] = field(default_factory=list)
    length: int = 0

    def silence(self, seconds: float) -> None:
        n = int(round(seconds * self.rate))
        self.parts.append(np.zeros(n, dtype=np.float32))
        self.length += n

    def add(self, speech: np.ndarray, lead: float = 0.30, tail: float = 0.60) -> Clip:
        """Append lead silence, speech, tail silence. lead must exceed CLIP_LEAD and tail CLIP_TAIL."""
        assert lead > CLIP_LEAD + 0.05 and tail > CLIP_TAIL + 0.05, "pads must leave clip times inside the silence"
        self.silence(lead)
        start = self.length / self.rate
        self.parts.append(speech.astype(np.float32))
        self.length += len(speech)
        end = self.length / self.rate
        self.silence(tail)
        return Clip(start, end)

    @property
    def seconds(self) -> float:
        return self.length / self.rate

    def samples(self) -> np.ndarray:
        return np.concatenate(self.parts) if self.parts else np.zeros(0, dtype=np.float32)


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    import soundfile as sf

    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 0.99:
        samples = samples * (0.99 / peak)
    sf.write(path, samples, rate, subtype="PCM_16")


def loudness(path: Path) -> dict:
    """EBU R128 / ITU-R BS.1770 measurement via ffmpeg's loudnorm filter."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return json.loads(out[out.rindex("{") : out.rindex("}") + 1])


def normalize(path: Path, target_lufs: float = -18.0, true_peak: float = -1.5) -> dict:
    """Linear gain to the integrated-loudness target, so clip timing is untouched."""
    m = loudness(path)
    tmp = path.with_suffix(".norm.wav")
    filt = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:linear=true:"
        f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
        f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
    )
    rate = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-af", filt, "-ar", rate, "-c:a", "pcm_s16le", str(tmp)], check=True)
    tmp.replace(path)
    return loudness(path)


def encode_mp3(wav: Path, mp3: Path, bitrate: str = "48k") -> None:
    """Mono, constant bitrate, as Spec 1203 §3.2.3 requires of the delivery codec."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1", "-c:a", "libmp3lame", "-b:a", bitrate, str(mp3)], check=True)
