"""Copy a finished build into sample/, the folder GitHub Pages serves.
Leaves out the WAV masters; keeps the DTB, the inspector page and the reports.

    python scripts/publish_sample.py build
"""
import shutil
import sys
from pathlib import Path

build, sample = Path(sys.argv[1] if len(sys.argv) > 1 else "build"), Path("sample")
shutil.rmtree(sample, ignore_errors=True)
shutil.copytree(build / "dtb", sample / "dtb")
for name in ("index.html", "build-report.json", "validation.json", "intelligibility.json", "plan.json"):
    shutil.copy(build / name, sample / name)
print(f"{sum(p.stat().st_size for p in sample.rglob('*') if p.is_file()) / 1e6:.1f} MB in {sample}/")
