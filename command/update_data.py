"""
update_data.py — Script cập nhật dữ liệu hằng ngày (Smart Incremental).

Luồng:
    1. Đọc danh sách mã từ tickers.csv
    2. Nếu market_data.csv đã tồn tại → incremental (chỉ tải ngày mới)
    3. Nếu chưa có hoặc --backfill → tải toàn bộ lookback
    4. Gộp thành 1 DataFrame (index=ngày, columns=mã)
    5. Lưu vào data_lake/market_data.csv

Usage:
    python command/update_data.py                    # incremental (default)
    python command/update_data.py --backfill 2190    # backfill ~6 năm
    python command/update_data.py --from-date 2019-01-01
"""
import os
import time
import logging
import argparse
import pandas as pd
from datetime import datetime, timedelta
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Ép import config ở ROOT project thay vì command/config.py
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import (
    VNSTOCK_API_KEY,
    DATA_LAKE,
    MARKET_DATA,
    VNINDEX_DATA,
    TICKERS_FILE,
    DEFAULT_LOOKBACK_DAYS,
)

os.environ["VNSTOCK_API_KEY"] = VNSTOCK_API_KEY


def load_tickers() -> list:
    """Đọc danh sách mã từ tickers.csv."""
    try:
        tickers = (
            pd.read_csv(TICKERS_FILE)["Ticker"]
            .dropna()
            .str.strip()
            .str.upper()
            .tolist()
        )
        logger.info("Đọc được %d mã từ %s", len(tickers), TICKERS_FILE)
        return tickers
    except FileNotFoundError:
        logger.error("Không tìm thấy %s — tạo file và thêm mã vào.", TICKERS_FILE)
        return []


def fetch_close(symbol: str, start: str, end: str, source: str = "VCI") -> pd.Series | None:
    """
    Tải giá đóng cửa cho 1 mã.
    Trả về None nếu không tải được — KHÔNG raise exception.
    """
    try:
        from vnstock import Quote
        df = Quote(symbol=symbol, source=source).history(
            start=start, end=end, interval="1D"
        )
        if df is None or df.empty:
            logger.warning("%-6s — API trả về rỗng, bỏ qua.", symbol)
            return None

        s = (
            df[["time", "close"]]
            .rename(columns={"close": symbol})
            .set_index("time")
        )
        s.index = pd.to_datetime(s.index).normalize().tz_localize(None)
        s = s[~s.index.duplicated(keep="last")]
        logger.info("✓ %-8s [%s] — %d ngày", symbol, source, len(s))
        return s[symbol]

    except Exception as e:
        logger.warning("✗ %-8s [%s] — %s — bỏ qua.", symbol, source, e)
        return None


def _load_existing_market_data(path: Path) -> pd.DataFrame | None:
    """Đọc file market_data.csv hiện có, trả về DataFrame hoặc None."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        logger.info("Đã đọc file hiện có: %d ngày × %d mã, last_date=%s",
                    df.shape[0], df.shape[1], df.index.max().strftime('%Y-%m-%d'))
        return df
    except Exception as e:
        logger.warning("Không đọc được file cũ %s: %s — sẽ tạo mới.", path, e)
        return None


def _merge_and_save(df_new: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Merge data mới vào file cũ (nếu có). df_new ưu tiên, NaN không ghi đè data cũ."""
    df_old = _load_existing_market_data(path)
    if df_old is not None:
        # df_new.combine_first(df_old): union index, ưu tiên df_new (nếu non-NaN), fallback df_old
        df_merged = df_new.combine_first(df_old).sort_index()
    else:
        df_merged = df_new.sort_index()

    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(path)
    logger.info("Đã lưu: %d ngày × %d mã → %s", df_merged.shape[0], df_merged.shape[1], path)
    return df_merged


def update_vnindex(start: str, end: str) -> bool:
    """
    Tải và lưu dữ liệu VNINDEX vào data_lake/vnindex_cache.csv.
    Trả về True nếu thành công.
    Ưu tiên VCI, fallback KBS.
    """
    logger.info("Đang tải VNINDEX...")
    s = fetch_close("VNINDEX", start, end, source="VCI")
    if s is None:
        logger.info("VNINDEX VCI thất bại, thử fallback KBS...")
        s = fetch_close("VNINDEX", start, end, source="KBS")
    if s is None:
        logger.warning("Không tải được VNINDEX, bỏ qua lưu file VNINDEX.")
        return False

    df_new = s.to_frame(name="VNINDEX").sort_index().ffill()
    _merge_and_save(df_new, VNINDEX_DATA)
    return True


def update(backfill_days: int | None = None, from_date: str | None = None):
    logger.info("Dùng DATA_LAKE: %s", DATA_LAKE)
    logger.info("Dùng MARKET_DATA: %s", MARKET_DATA)
    logger.info("Dùng TICKERS_FILE: %s", TICKERS_FILE)
    if "/command/data_lake" in str(DATA_LAKE).replace("\\", "/"):
        raise RuntimeError(f"Sai output path: {DATA_LAKE} (phải là root data_lake)")

    tickers = load_tickers()
    if not tickers:
        logger.error("tickers.csv trống. Thêm mã vào rồi chạy lại.")
        return

    # Xác định khoảng thờ gian cần tải
    df_existing = _load_existing_market_data(MARKET_DATA)
    today_str = datetime.now().strftime("%Y-%m-%d")

    if from_date:
        start = from_date
        logger.info("Mode: BACKFILL from %s", start)
    elif backfill_days:
        start = (datetime.now() - timedelta(days=backfill_days)).strftime("%Y-%m-%d")
        logger.info("Mode: BACKFILL %d days → %s", backfill_days, start)
    elif df_existing is not None:
        # Incremental: tải từ ngày cuối file đến hôm nay
        last_date = df_existing.index.max()
        # Lùi 3 ngày để catch-up nếu có gap
        start_date = last_date - timedelta(days=3)
        start = start_date.strftime("%Y-%m-%d")
        logger.info("Mode: INCREMENTAL from %s (last_date=%s)", start, last_date.strftime('%Y-%m-%d'))
    else:
        start = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        logger.info("Mode: FULL (file chưa tồn tại) from %s", start)

    end = datetime.now().strftime("%Y-%m-%d")
    logger.info("Khoảng thờ gian: %s → %s", start, end)

    update_vnindex(start, end)

    # Dữ liệu cổ phiếu chỉ giữ universe equity/ETF, loại VNINDEX khỏi market_data
    stock_tickers = [t for t in tickers if t != "VNINDEX"]
    if not stock_tickers:
        logger.error("Không có ticker cổ phiếu hợp lệ sau khi loại VNINDEX.")
        return

    series_list = []
    failed = []

    for i, symbol in enumerate(stock_tickers, 1):
        logger.info("[%d/%d] Đang tải %s...", i, len(stock_tickers), symbol)
        s = fetch_close(symbol, start, end, source="VCI")
        if s is None:
            logger.info("  %s VCI thất bại, thử fallback KBS...", symbol)
            s = fetch_close(symbol, start, end, source="KBS")
        if s is not None:
            series_list.append(s)
        else:
            failed.append(symbol)
        time.sleep(1)  # rate limit

    logger.info("─" * 50)
    logger.info("Thành công: %d / %d mã", len(series_list), len(stock_tickers))

    if failed:
        logger.warning("Bỏ qua %d mã: %s", len(failed), ", ".join(failed))

    if len(series_list) < 2:
        logger.error("Chưa đủ dữ liệu (< 2 mã) — không lưu file.")
        return

    df_new = pd.concat(series_list, axis=1).sort_index().ffill()
    _merge_and_save(df_new, MARKET_DATA)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cập nhật dữ liệu giá từ VNStock")
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="Backfill N ngày lịch sử (ví dụ: 2190 ~ 6 năm)")
    parser.add_argument("--from-date", type=str, metavar="YYYY-MM-DD",
                        help="Backfill từ ngày cụ thể")
    args = parser.parse_args()

    update(backfill_days=args.backfill, from_date=args.from_date)
