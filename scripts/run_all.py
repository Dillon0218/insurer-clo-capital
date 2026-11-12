"""Rerun the whole pipeline from the committed data: python scripts/run_all.py"""
from __future__ import annotations

import runpy
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    "01_calibration.py",
    "02_simulation.py",
    "03_recession.py",
    "04_validation.py",
    "05_sensitivity.py",
    "06_figures.py",
    "07_headline.py",
]


def main() -> None:
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent / "src"))
    from clo.context import check_licensed
    check_licensed()            # S&P / Moody's tables live in data/licensed, outside git
    start = time.time()
    for step in STEPS:
        t0 = time.time()
        print(f"\n=== {step} ===")
        runpy.run_path(str(HERE / step), run_name="__main__")
        print(f"--- {step} done in {time.time() - t0:.0f}s")
    print(f"\nall steps done in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
