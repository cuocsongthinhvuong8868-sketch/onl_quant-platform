"""
Regenerate VN100 Corporate Health Monitor outputs.

Usage:
    python -m command.update_vn100_corporate_health
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.vn100_earnings_health.quant.pipeline import run_and_write


def main() -> None:
    _, summary = run_and_write()
    print("VN100 Corporate Health Monitor pipeline complete")
    for key, value in summary.items():
        if key == "files":
            print(f"{key}: {len(value)} files")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
