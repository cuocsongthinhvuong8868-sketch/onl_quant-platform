"""Refresh credit-spread CSV snapshots from an LTMM silver-data directory."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATA_LAKE
from tools.credit_spread.quant.metrics import (
    AGGREGATED_REQUIRED_COLUMNS,
    GOVERNMENT_REQUIRED_COLUMNS,
    ISSUANCE_REQUIRED_COLUMNS,
)


FILES_AND_SCHEMAS = {
    "vbma_corp_bond_issuance_detail.csv": ISSUANCE_REQUIRED_COLUMNS,
    "vbma_corp_bond_yields.csv": AGGREGATED_REQUIRED_COLUMNS,
    "bond_yields_vn.csv": GOVERNMENT_REQUIRED_COLUMNS,
}


def default_source_dir() -> Path:
    configured = os.getenv("LTMM_SILVER_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Desktop" / "LTMM" / "data" / "silver"


def refresh_credit_spread_data(source_dir: Path, destination_dir: Path) -> list[Path]:
    """Validate each source header, then replace all three destination files."""
    source_dir = source_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    missing_files = [name for name in FILES_AND_SCHEMAS if not (source_dir / name).is_file()]
    if missing_files:
        raise FileNotFoundError(f"Thieu file trong {source_dir}: {missing_files}")

    for name, required in FILES_AND_SCHEMAS.items():
        columns = set(pd.read_csv(source_dir / name, nrows=0).columns)
        missing_columns = sorted(required.difference(columns))
        if missing_columns:
            raise ValueError(f"{name} thieu cot: {missing_columns}")

    written: list[Path] = []
    for name in FILES_AND_SCHEMAS:
        destination = destination_dir / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source_dir / name, temporary)
        temporary.replace(destination)
        written.append(destination)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=default_source_dir())
    parser.add_argument("--destination-dir", type=Path, default=DATA_LAKE / "credit_spread")
    args = parser.parse_args()

    written = refresh_credit_spread_data(args.source_dir, args.destination_dir)
    for path in written:
        print(f"[OK] {path}")


if __name__ == "__main__":
    main()
