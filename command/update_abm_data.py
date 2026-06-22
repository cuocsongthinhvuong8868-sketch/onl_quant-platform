"""Sync ABM gold CSV files from the LTMM project into Quant Platform."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_LAKE = ROOT_DIR / "data_lake"
DEFAULT_LTMM_GOLD_DIR = Path(
    os.getenv("LTMM_GOLD_DIR", r"C:\Users\ADMIN\Desktop\LTMM\data\gold")
)

REQUIRED_TABLES = [
    "abm_behavioral_state",
    "abm_stress_test",
    "abm_alert",
]
OPTIONAL_TABLES = [
    "abm_latent_state",
    "abm_validation",
]
ALL_TABLES = REQUIRED_TABLES + OPTIONAL_TABLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def sync_abm_data(source_dir: Path = DEFAULT_LTMM_GOLD_DIR, strict: bool = False) -> bool:
    """Copy ABM gold CSV files from LTMM into `data_lake`.

    Required tables are the minimum needed by the dashboard. Optional latent and
    validation tables are copied when present and enrich the diagnostics view.
    """
    source_dir = Path(source_dir)
    if not source_dir.exists():
        logger.warning("LTMM gold directory not found: %s", source_dir)
        return False if strict else True

    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for table in ALL_TABLES:
        src_path = source_dir / f"{table}.csv"
        dest_path = DATA_LAKE / f"{table}.csv"
        if not src_path.exists():
            if table in REQUIRED_TABLES:
                missing_required.append(table)
            else:
                missing_optional.append(table)
            continue
        shutil.copy2(src_path, dest_path)
        copied.append(table)
        logger.info("Copied %s -> %s", src_path, dest_path)

    if missing_optional:
        logger.info("Optional ABM files not found: %s", ", ".join(missing_optional))
    if missing_required:
        logger.error("Required ABM files not found: %s", ", ".join(missing_required))
        return False

    logger.info("ABM sync complete: copied %d/%d files.", len(copied), len(ALL_TABLES))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_LTMM_GOLD_DIR,
        help="LTMM gold directory containing abm_*.csv files.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when the source directory itself is missing.",
    )
    args = parser.parse_args(argv)
    return 0 if sync_abm_data(args.source_dir, strict=args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())

