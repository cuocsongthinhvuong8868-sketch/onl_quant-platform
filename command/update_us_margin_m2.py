"""
Update US margin debt / M2 overlay cache.

The output is monthly and is not part of Global FCI PCA. It is consumed as a
dashboard/AI CIO overlay only.

Usage:
  python command/update_us_margin_m2.py
  python command/update_us_margin_m2.py --allow-stale
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_LAKE
from tools.global_financial_conditions.quant.margin_m2 import (
    MARGIN_M2_CACHE,
    MARGIN_M2_START_DATE,
    combine_margin_and_m2,
    fetch_finra_margin_debt,
    fetch_fred_m2,
    summarize_latest_margin_m2,
    validate_margin_m2,
)


def _resolve_fred_api_key(cli_key: str | None = None) -> str:
    if cli_key:
        return cli_key
    key = os.getenv("FRED_API_KEY", "")
    if key:
        return key
    try:
        from config import FRED_API_KEY as config_key

        if config_key:
            return config_key
    except Exception:
        pass
    return ""


def update_us_margin_m2(
    api_key: str,
    finra_url: str | None = None,
    start_date: str = MARGIN_M2_START_DATE,
    allow_stale: bool = False,
) -> pd.DataFrame:
    logger.info("Đang fetch FINRA margin debt...")
    finra_df = fetch_finra_margin_debt(finra_url)
    logger.info("  ✓ FINRA rows: %d", len(finra_df))

    logger.info("Đang fetch FRED M2 (%s)...", start_date)
    m2_df = fetch_fred_m2(api_key, observation_start=start_date)
    logger.info("  ✓ FRED M2 rows: %d", len(m2_df))

    logger.info("Đang join monthly + tính Margin/M2 overlay...")
    df = combine_margin_and_m2(finra_df, m2_df)
    validate_margin_m2(df, allow_stale=allow_stale)

    save = df.copy()
    save["date"] = pd.to_datetime(save["date"]).dt.strftime("%Y-%m-%d")
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    save.to_csv(MARGIN_M2_CACHE, index=False)
    logger.info("  ✓ Lưu %s (%d rows)", MARGIN_M2_CACHE, len(save))

    latest = summarize_latest_margin_m2(df)
    logger.info(
        "Latest: %s | Margin/M2=%.2f%% | z5y=%s | pct10y=%s | regime=%s",
        latest["date"],
        latest["margin_debt_pct_m2"] or 0.0,
        _fmt(latest["margin_debt_pct_m2_zscore_5y"]),
        _fmt(latest["margin_debt_pct_m2_percentile_10y"]),
        latest["signal_regime"],
    )
    return df


def _fmt(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}"


def main():
    parser = argparse.ArgumentParser(description="Update US margin debt / M2 overlay cache")
    parser.add_argument("--api-key", type=str, default=None, help="FRED API key override")
    parser.add_argument("--finra-url", type=str, default=None, help="FINRA Excel URL override")
    parser.add_argument("--from-date", type=str, default=MARGIN_M2_START_DATE)
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Allow latest FINRA month to be older than the freshness check.",
    )
    args = parser.parse_args()

    api_key = _resolve_fred_api_key(args.api_key)
    if not api_key:
        logger.error("Thiếu FRED_API_KEY trong env/config hoặc --api-key.")
        sys.exit(1)

    try:
        update_us_margin_m2(
            api_key=api_key,
            finra_url=args.finra_url,
            start_date=args.from_date,
            allow_stale=args.allow_stale,
        )
    except Exception as exc:
        logger.error(str(exc))
        sys.exit(2)


if __name__ == "__main__":
    main()
