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
import numpy as np
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
    MARKET_VOLUME,
    VNINDEX_DATA,
    VN30_DATA,
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


def fetch_history(symbol: str, start: str, end: str, source: str = "VCI") -> pd.DataFrame | None:
    """
    Tải lịch sử OHLCV cho 1 mã, trả về DataFrame [close, volume] (index=date).
    Trả về None nếu không tải được — KHÔNG raise exception.

    Volume = NaN nếu nguồn không cung cấp (vd. KBS cho index có thể thiếu);
    caller phải xử lý NaN volume (vd. fill 0 hoặc skip).
    """
    try:
        from vnstock import Quote
        df = Quote(symbol=symbol, source=source).history(
            start=start, end=end, interval="1D"
        )
        if df is None or df.empty:
            logger.warning("%-6s — API trả về rỗng, bỏ qua.", symbol)
            return None

        keep_cols = ["time", "close"]
        if "volume" in df.columns:
            keep_cols.append("volume")

        out = df[keep_cols].set_index("time")
        out.index = pd.to_datetime(out.index).normalize().tz_localize(None)
        out = out[~out.index.duplicated(keep="last")]

        if "volume" not in out.columns:
            out["volume"] = np.nan
            logger.info("✓ %-8s [%s] — %d ngày (volume thiếu, fill NaN)", symbol, source, len(out))
        else:
            logger.info("✓ %-8s [%s] — %d ngày (close+vol)", symbol, source, len(out))
        return out[["close", "volume"]]

    except Exception as e:
        logger.warning("✗ %-8s [%s] — %s — bỏ qua.", symbol, source, e)
        return None


# Backwards-compat: code cũ vẫn import fetch_close
def fetch_close(symbol: str, start: str, end: str, source: str = "VCI") -> pd.Series | None:
    """Wrapper giữ tương thích — trả về Series close only."""
    df = fetch_history(symbol, start, end, source)
    if df is None:
        return None
    return df["close"].rename(symbol)


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


def _fetch_index_with_fallback(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    """Fetch index (VNINDEX/VN30) với fallback VCI → KBS. Trả về DF [close, volume]."""
    df = fetch_history(symbol, start, end, source="VCI")
    if df is None:
        logger.info("%s VCI thất bại, thử fallback KBS...", symbol)
        df = fetch_history(symbol, start, end, source="KBS")
    return df


def update_vnindex(start: str, end: str) -> bool:
    """Tải VNINDEX (close + volume) vào data_lake/vnindex_cache.csv.

    Cột: VNINDEX, VNINDEX_volume.
    close ffill (để skip ngày nghỉ); volume KHÔNG ffill (NaN giữ nguyên =
    ngày không giao dịch → 0 sẽ làm méo Amihud).
    """
    logger.info("Đang tải VNINDEX...")
    df = _fetch_index_with_fallback("VNINDEX", start, end)
    if df is None:
        logger.warning("Không tải được VNINDEX, bỏ qua lưu file VNINDEX.")
        return False

    df_new = df.rename(columns={"close": "VNINDEX", "volume": "VNINDEX_volume"}).sort_index()
    df_new["VNINDEX"] = df_new["VNINDEX"].ffill()
    _merge_and_save(df_new, VNINDEX_DATA)
    return True


def update_vn30(start: str, end: str) -> bool:
    """Tải VN30 index (close + volume) vào data_lake/vn30_cache.csv.

    Cột: VN30, VN30_volume. Volume cần thiết cho ESR Monitor S_PRES.
    """
    logger.info("Đang tải VN30...")
    df = _fetch_index_with_fallback("VN30", start, end)
    if df is None:
        logger.warning("Không tải được VN30, bỏ qua lưu file VN30.")
        return False

    df_new = df.rename(columns={"close": "VN30", "volume": "VN30_volume"}).sort_index()
    df_new["VN30"] = df_new["VN30"].ffill()
    _merge_and_save(df_new, VN30_DATA)
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
    update_vn30(start, end)

    # Dữ liệu cổ phiếu — loại VNINDEX và VN30 khỏi market_data (lưu riêng)
    stock_tickers = [t for t in tickers if t not in ("VNINDEX", "VN30")]
    if not stock_tickers:
        logger.error("Không có ticker cổ phiếu hợp lệ sau khi loại VNINDEX.")
        return

    close_list = []
    volume_list = []
    failed = []

    for i, symbol in enumerate(stock_tickers, 1):
        logger.info("[%d/%d] Đang tải %s...", i, len(stock_tickers), symbol)
        df_hist = fetch_history(symbol, start, end, source="VCI")
        if df_hist is None:
            logger.info("  %s VCI thất bại, thử fallback KBS...", symbol)
            df_hist = fetch_history(symbol, start, end, source="KBS")
        if df_hist is not None:
            close_list.append(df_hist["close"].rename(symbol))
            volume_list.append(df_hist["volume"].rename(symbol))
        else:
            failed.append(symbol)
        time.sleep(1)  # rate limit

    logger.info("─" * 50)
    logger.info("Thành công: %d / %d mã", len(close_list), len(stock_tickers))

    if failed:
        logger.warning("Bỏ qua %d mã: %s", len(failed), ", ".join(failed))

    if len(close_list) < 2:
        logger.error("Chưa đủ dữ liệu (< 2 mã) — không lưu file.")
        return

    # close: ffill để skip cuối tuần / lễ
    df_close = pd.concat(close_list, axis=1).sort_index().ffill()
    _merge_and_save(df_close, MARKET_DATA)

    # volume: KHÔNG ffill (volume = 0 hoặc NaN giữ ý nghĩa "không giao dịch")
    df_volume = pd.concat(volume_list, axis=1).sort_index()
    # Sanitize: thay <0 / inf bằng NaN; cho phép 0 thật
    df_volume = df_volume.replace([np.inf, -np.inf], np.nan)
    df_volume = df_volume.mask(df_volume < 0, np.nan)
    _merge_and_save(df_volume, MARKET_VOLUME)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cập nhật dữ liệu giá từ VNStock")
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="Backfill N ngày lịch sử (ví dụ: 2190 ~ 6 năm)")
    parser.add_argument("--from-date", type=str, metavar="YYYY-MM-DD",
                        help="Backfill từ ngày cụ thể")
    args = parser.parse_args()

    update(backfill_days=args.backfill, from_date=args.from_date)
