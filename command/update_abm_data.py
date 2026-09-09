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
DEFAULT_LTMM_INTEGRATION_DIR = Path(
    os.getenv("LTMM_INTEGRATION_DIR", r"C:\Users\ADMIN\Desktop\LTMM\quant_platform_intergration\data_LTMM")
)

REQUIRED_TABLES = [
    "abm_behavioral_state",
    "abm_stress_test",
    "abm_alert",
]
OPTIONAL_TABLES = [
    "abm_latent_state",
    "abm_validation",
    "abm_scenario_grid",
]
ALL_TABLES = REQUIRED_TABLES + OPTIONAL_TABLES
LTMM_PAYLOAD_DIRS = [
    "sourse_raw",  # Existing folder spelling used by the LTMM and Quant Platform UI.
    "AI_CIO_raw",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _copy_tree_contents(source_dir: Path, target_dir: Path) -> int:
    copied = 0
    target_dir.mkdir(parents=True, exist_ok=True)
    for src_path in source_dir.rglob("*"):
        if not src_path.is_file():
            continue
        dest_path = target_dir / src_path.relative_to(source_dir)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        copied += 1
    return copied


def sync_abm_data(
    source_dir: Path = DEFAULT_LTMM_GOLD_DIR,
    strict: bool = False,
    integration_dir: Path = DEFAULT_LTMM_INTEGRATION_DIR,
    include_ltmm_payloads: bool = True,
) -> bool:
    """Copy ABM gold CSV files and LTMM payloads into `data_lake`.

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
    if include_ltmm_payloads:
        integration_dir = Path(integration_dir)
        if not integration_dir.exists():
            logger.warning("LTMM integration payload directory not found: %s", integration_dir)
            return False if strict else True

        total_payload_files = 0
        for folder in LTMM_PAYLOAD_DIRS:
            src_dir = integration_dir / folder
            dest_dir = DATA_LAKE / "data_LTMM" / folder
            if not src_dir.exists():
                logger.warning("LTMM payload folder not found: %s", src_dir)
                if strict:
                    return False
                continue
            files_copied = _copy_tree_contents(src_dir, dest_dir)
            total_payload_files += files_copied
            logger.info("Copied LTMM payload %s -> %s (%d files)", src_dir, dest_dir, files_copied)
        logger.info("LTMM payload sync complete: copied %d files.", total_payload_files)
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
    parser.add_argument(
        "--integration-dir",
        type=Path,
        default=DEFAULT_LTMM_INTEGRATION_DIR,
        help="LTMM data_LTMM integration directory containing sourse_raw and AI_CIO_raw.",
    )
    parser.add_argument(
        "--skip-ltmm-payloads",
        action="store_true",
        help="Only copy ABM CSVs; do not copy data_LTMM payload folders.",
    )
    args = parser.parse_args(argv)
    return 0 if sync_abm_data(
        args.source_dir,
        strict=args.strict,
        integration_dir=args.integration_dir,
        include_ltmm_payloads=not args.skip_ltmm_payloads,
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
