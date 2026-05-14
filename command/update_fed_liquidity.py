"""
command/update_fed_liquidity.py — Updater Fed Liquidity Monitor.

Luồng:
  1. Gọi FRED API lấy 3 series: WALCL, WTREGEN, RRPONTSYD
  2. Tính Net Liquidity + Impulse + Z-Score + Signal
  3. Lưu vào data_lake/fed_liquidity_cache.csv

Usage:
  python command/update_fed_liquidity.py

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
from tools.fed_liquidity.quant.metrics import (
    fetch_fed_data,
    process_liquidity_logic,
    START_DATE,
    OUTPUT_COLUMNS,
)

FED_LIQUIDITY_FILE = DATA_LAKE / "fed_liquidity_cache.csv"


def _resolve_fred_api_key(cli_key: str | None = None) -> str:
    """Ưu tiên CLI arg → env var → config (nếu có)."""
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


def update_fed_liquidity(api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Pull FRED → process → save CSV.

    Returns
    -------
    pd.DataFrame processed (đã filter từ start_date).
    """
    logger.info("Đang kết nối FRED API...")
    df_raw = fetch_fed_data(api_key)
    logger.info("  ✓ Đã tải raw FRED data: %d rows", len(df_raw))

    logger.info("Đang xử lý logic thanh khoản (resample W-WED + Net Liq + Z-Score)...")
    df_processed = process_liquidity_logic(df_raw, start_date=start_date)
    logger.info("  ✓ Xử lý xong: %d tuần dữ liệu", len(df_processed))

    if df_processed.empty:
        logger.warning("DataFrame rỗng sau khi xử lý — không lưu file.")
        return df_processed

    df_save = df_processed.reset_index()
    df_save["DATE"] = df_save["DATE"].dt.strftime("%Y-%m-%d")

    cols_to_save = ["DATE"] + OUTPUT_COLUMNS
    df_save = df_save[cols_to_save]

    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df_save.to_csv(FED_LIQUIDITY_FILE, index=False)
    logger.info("  ✓ Lưu %s (%d rows)", FED_LIQUIDITY_FILE, len(df_save))

    # Print signal summary
    latest = df_save.iloc[-1]
    logger.info(
        "Latest: %s | Net Liq=%s | Z=%s | Signal=%s",
        latest["DATE"],
        f"{float(latest['Net_Liquidity']):,.0f}",
        f"{float(latest['Z_Score']):+.2f}" if pd.notna(latest["Z_Score"]) else "N/A",
        latest["Signal"],
    )
    return df_processed


def main():
    parser = argparse.ArgumentParser(description="Update Fed Liquidity cache từ FRED API")
    parser.add_argument("--api-key", type=str, default=None, help="FRED API key (override env)")
    parser.add_argument("--from-date", type=str, default=START_DATE,
                        help=f"Ngày bắt đầu lọc kết quả (default: {START_DATE})")
    args = parser.parse_args()

    api_key = _resolve_fred_api_key(args.api_key)
    if not api_key:
        logger.error(
            "Thiếu FRED_API_KEY. Hãy:\n"
            "  - Set biến môi trường: export FRED_API_KEY=xxx\n"
            "  - Hoặc thêm FRED_API_KEY=xxx vào file .env\n"
            "  - Hoặc truyền --api-key xxx"
        )
        sys.exit(1)

    try:
        update_fed_liquidity(api_key, start_date=args.from_date)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
