"""
command/update_global_financial_conditions.py
Updater Global Financial Conditions Monitor (GFCM).

Luồng:
  1. Pull VIX + HY_OAS + CCC_OAS từ FRED (VIXCLS / BAMLH0A0HYM2 / BAMLH0A3HYC)
  2. Pull MOVE từ Yahoo Finance (^MOVE) qua yfinance
  3. Compute rolling z-score + percentile rank 252d (1Y), static PCA, regime + driver
  4. Lưu vào data_lake/global_financial_conditions_cache.csv

Usage:
  python command/update_global_financial_conditions.py

Env:
  FRED_API_KEY=<your_fred_api_key>
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
from tools.global_financial_conditions.quant.metrics import (
    fetch_raw_data,
    process_gfcm_logic,
    START_DATE,
    OUTPUT_COLUMNS,
)

GFCM_FILE = DATA_LAKE / "global_financial_conditions_cache.csv"


def _resolve_fred_api_key(cli_key: str | None = None) -> str:
    if cli_key:
        return cli_key
    key = os.getenv("FRED_API_KEY", "")
    if key:
        return key
    try:
        from config import FRED_API_KEY as _CK
        if _CK:
            return _CK
    except Exception:
        pass
    return ""


def update_gfcm(api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    logger.info("Đang fetch raw data (FRED + Yahoo)...")
    df_raw = fetch_raw_data(api_key, start_date=start_date)
    logger.info("  ✓ Raw rows: %d (cols: %s)", len(df_raw), list(df_raw.columns))

    logger.info("Đang process: z-score + percentile + PCA + regime...")
    df_processed, meta = process_gfcm_logic(df_raw)
    logger.info("  ✓ Processed rows: %d", len(df_processed))

    if meta and meta.get("loadings") is not None:
        loadings = meta["loadings"]
        evr = meta.get("explained_variance_ratio", [])
        logger.info(
            "  PCA explained variance: PC1=%.1f%% · PC2=%.1f%%",
            evr[0] * 100 if len(evr) > 0 else 0,
            evr[1] * 100 if len(evr) > 1 else 0,
        )
        logger.info("  PC1 loadings: %s",
                    {k: round(v, 3) for k, v in loadings["PC1"].to_dict().items()})
        logger.info("  PC2 loadings: %s",
                    {k: round(v, 3) for k, v in loadings["PC2"].to_dict().items()})
        logger.info("  %s", meta.get("pc2_interpretation", ""))

    if df_processed.empty:
        logger.warning("DataFrame rỗng — không lưu file.")
        return df_processed

    df_save = df_processed.reset_index()
    df_save["DATE"] = df_save["DATE"].dt.strftime("%Y-%m-%d")
    cols_to_save = ["DATE"] + OUTPUT_COLUMNS
    df_save = df_save[cols_to_save]

    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df_save.to_csv(GFCM_FILE, index=False)
    logger.info("  ✓ Lưu %s (%d rows)", GFCM_FILE, len(df_save))

    # Print latest summary
    df_clean = df_processed.dropna(subset=["PC1_pct"])
    if not df_clean.empty:
        latest = df_clean.iloc[-1]
        logger.info(
            "Latest: %s | PC1=%+.2f (pct=%.0f%%) | Regime=%s | Driver=%s",
            df_clean.index[-1].strftime("%Y-%m-%d"),
            float(latest["PC1"]),
            float(latest["PC1_pct"]) * 100,
            latest["Regime"],
            latest["Driver"],
        )
    return df_processed


def main():
    parser = argparse.ArgumentParser(
        description="Update Global Financial Conditions cache (VIX + MOVE + HY/CCC OAS)"
    )
    parser.add_argument("--api-key", type=str, default=None,
                        help="FRED API key (override env)")
    parser.add_argument("--from-date", type=str, default=START_DATE,
                        help=f"Ngày bắt đầu fetch (default: {START_DATE})")
    args = parser.parse_args()

    api_key = _resolve_fred_api_key(args.api_key)
    if not api_key:
        logger.error(
            "Thiếu FRED_API_KEY. Hãy:\n"
            "  - export FRED_API_KEY=xxx, hoặc\n"
            "  - thêm FRED_API_KEY=xxx vào .env, hoặc\n"
            "  - truyền --api-key xxx"
        )
        sys.exit(1)

    try:
        update_gfcm(api_key, start_date=args.from_date)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
