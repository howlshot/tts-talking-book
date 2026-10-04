"""Intelligibility check: transcribe each finished track and score it against the
text the voice was given (word error rate). Uses whisper.cpp, run locally."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

NUMBERS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
ROMAN = {r: str(i) for i, r in enumerate("i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx xxi xxii xxiii xxiv xxv xxvi xxvii".split(), 1)}
NUMBERED = {"article", "amendment", "section", "part", "chapter"}
MODEL = Path.home() / ".cache/whisper.cpp/ggml-small.en.bin"


def words(text: str) -> list[str]:
    text = text.lower().replace("&", " and ").replace("’", "'")
    out: list[str] = []
    for w in re.findall(r"[a-z0-9']+", text):
        w = w.strip("'")
        if out and out[-1] in NUMBERED and w in ROMAN:  # "Article III" -> "article 3"
            w = ROMAN[w]
        out.append(NUMBERS.get(w, w))
    return [w for w in out if w]


def wer(reference: list[str], hypothesis: list[str]) -> tuple[int, int]:
    """Word-level edit distance (substitutions + deletions + insertions) and reference length."""
    prev = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, 1):
        cur = [i] + [0] * len(hypothesis)
        for j, h in enumerate(hypothesis, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1], len(reference)


def transcribe(wav: Path, model: Path = MODEL) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        mono = Path(tmp) / "in.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-ar", "16000", "-ac", "1", str(mono)], check=True)
        subprocess.run(["whisper-cli", "-m", str(model), "-f", str(mono), "-otxt", "-of", str(Path(tmp) / "out")], check=True, capture_output=True)
        return (Path(tmp) / "out.txt").read_text()


def score(out: Path) -> dict:
    plan = json.loads((out / "plan.json").read_text())
    tracks: dict[str, list[str]] = {}
    for p in plan["pars"]:
        tracks.setdefault(p["audio"], []).append(p["said"])
    rows, errors, total = [], 0, 0
    for name, said in tracks.items():
        hyp = transcribe(out / "masters" / name.replace(".mp3", ".wav"))
        e, n = wer(words(" ".join(said)), words(hyp))
        rows.append({"file": name, "words": n, "errors": e, "wer": round(e / n, 4) if n else 0.0})
        errors, total = errors + e, total + n
    result = {"engine": f"whisper.cpp {MODEL.name}", "words": total, "errors": errors, "wer": round(errors / total, 4) if total else 0.0, "tracks": rows}
    (out / "intelligibility.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
