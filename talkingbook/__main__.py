"""Command line.

    python -m talkingbook build sources/constitution.json --out build
    python -m talkingbook validate build --pid tts000001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talkingbook")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="Build, validate and write the inspector page.")
    b.add_argument("config")
    b.add_argument("--out", default="build")
    b.add_argument("--voice", default="af_heart", help="Kokoro voice, e.g. af_heart, am_michael, bf_emma.")
    b.add_argument("--speed", type=float, default=0.95)
    b.add_argument("--no-asr", action="store_true", help="Skip the whisper.cpp intelligibility check.")
    v = sub.add_parser("validate", help="Validate an existing build.")
    v.add_argument("out")
    v.add_argument("--pid", required=True)
    v.add_argument("--no-asr", action="store_true")
    args = parser.parse_args(argv)

    from .inspect_page import page
    from .validate import validate

    if args.command == "build":
        from .build import Builder
        from .speech import Kokoro

        config = json.loads((ROOT / args.config).read_text())
        out = ROOT / args.out
        report = Builder(config, ROOT, out, Kokoro(args.voice, args.speed), args.voice).run()
        pid = config["pid"]
    else:
        out, pid = ROOT / args.out, args.pid
        report = json.loads((out / "build-report.json").read_text())

    result = validate(out, pid)
    (out / "validation.json").write_text(json.dumps(result.checks, indent=2) + "\n")
    intelligibility = None
    if not args.no_asr:
        from .asr import score

        intelligibility = score(out)
        print(f"intelligibility: {intelligibility['wer'] * 100:.1f}% word error rate over {intelligibility['words']} words")
    (out / "index.html").write_text(page(out, report, result.checks, intelligibility))
    for c in result.checks:
        print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['check']}" + (f"  ({c['detail']})" if c["detail"] else ""))
    print(f"{report['audio_seconds'] / 60:.1f} min of audio, {report['nav_points']} navPoints, synthesis {report['realtime_factor']}x real time, build {report['build_seconds']} s")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
