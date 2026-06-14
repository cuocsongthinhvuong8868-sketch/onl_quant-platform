"""
Copy raw MozyFin BCTC JSON feed for the native Bank Valuation tool.

Usage:
  python command/update_bank_valuation_data.py
  python command/update_bank_valuation_data.py --source-dir /path/to/BCTC/json
  python command/update_bank_valuation_data.py --manual-car /path/to/manual_car.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.bank_valuation.quant.pipeline import (  # noqa: E402
    BCTC_JSON_DIR,
    MANUAL_CAR_FILE,
    bank_valuation_source_signature,
)


DEFAULT_SOURCE_DIR = Path("/Users/macos/Desktop/bank_valuation/data/raw/BCTC_json")
DEFAULT_MANUAL_CAR = Path("/Users/macos/Desktop/bank_valuation/data/raw/manual_car.csv")


def _sanitize_bctc_payload(payload: dict) -> dict:
    return {
        "ticker": str(payload.get("ticker") or "").upper(),
        "url": payload.get("url", ""),
        "timestamp": payload.get("timestamp", ""),
        "financialData": payload.get("financialData", {}),
    }


def copy_bctc_json_feed(source_dir: Path, dest_dir: Path = BCTC_JSON_DIR, sanitize: bool = True) -> int:
    if not source_dir.exists():
        raise FileNotFoundError(source_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)
    for old_file in dest_dir.glob("*.json"):
        old_file.unlink()

    count = 0
    for path in sorted(source_dir.glob("*.json")):
        out_path = dest_dir / path.name
        if sanitize:
            payload = json.loads(path.read_text(encoding="utf-8"))
            out_path.write_text(
                json.dumps(_sanitize_bctc_payload(payload), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            shutil.copy2(path, out_path)
        count += 1
    return count


def copy_manual_car(source_file: Path, dest_file: Path = MANUAL_CAR_FILE) -> bool:
    if not source_file.exists():
        return False
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, dest_file)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Update native Bank Valuation raw JSON feed")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--dest-dir", type=Path, default=BCTC_JSON_DIR)
    parser.add_argument("--manual-car", type=Path, default=DEFAULT_MANUAL_CAR)
    parser.add_argument("--manual-car-dest", type=Path, default=MANUAL_CAR_FILE)
    parser.add_argument("--raw", action="store_true", help="Copy raw JSON instead of sanitized financialData-only JSON.")
    args = parser.parse_args()

    count = copy_bctc_json_feed(args.source_dir, args.dest_dir, sanitize=not args.raw)
    copied_car = copy_manual_car(args.manual_car, args.manual_car_dest)

    logger.info("Copied %d BCTC JSON files into %s", count, args.dest_dir)
    logger.info("Manual CAR file: %s", "copied" if copied_car else "not found, skipped")
    logger.info("Source signature: %s", bank_valuation_source_signature(args.dest_dir, args.manual_car_dest))


if __name__ == "__main__":
    main()
