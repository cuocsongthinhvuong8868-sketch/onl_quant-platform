"""Update PVGO valuation history from 24hmoney.

Usage:
  python command/update_pvgo_valuation.py
  python -m command.update_pvgo_valuation --dry-run
"""
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.pvgo.quant.valuation_24hmoney import main


if __name__ == "__main__":
    raise SystemExit(main())

