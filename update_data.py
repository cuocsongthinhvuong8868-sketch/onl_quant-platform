"""
update_data.py — Script cập nhật dữ liệu hằng ngày.

Luồng:
    1. Đọc danh sách mã từ tickers.csv
    2. Gọi VNStock API lấy giá đóng cửa từng mã
    3. Gộp thành 1 DataFrame (index=ngày, columns=mã)
    4. Lưu vào data_lake/market_data.csv

Lưu ý:
    - Nếu 1 mã không tải được → bỏ qua, KHÔNG fallback, KHÔNG dừng chương trình.
    - Chạy tay: python update_data.py
    - Hoặc đặt lịch tự động bằng cron / Task Scheduler.
"""
import os
import time
import logging
import pandas as pd
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

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


def fetch_close(symbol: str, start: str, end: str) -> pd.Series | None:
    """
    Tải giá đóng cửa cho 1 mã.
    Trả về None nếu không tải được — KHÔNG raise exception.
    """
    try:
        from vnstock import Quote
        df = Quote(symbol=symbol, source="KBS").history(
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
        logger.info("✓ %-6s — %d ngày", symbol, len(s))
        return s[symbol]

    except Exception as e:
        logger.warning("✗ %-6s — %s — bỏ qua.", symbol, e)
        return None


def update_vnindex(start: str, end: str) -> bool:
    """
    Tải và lưu dữ liệu VNINDEX vào data_lake/vnindex_cache.csv.
    Trả về True nếu thành công.
    """
    logger.info("Đang tải VNINDEX...")
    s = fetch_close("VNINDEX", start, end)
    if s is None:
        logger.warning("Không tải được VNINDEX, bỏ qua lưu file VNINDEX.")
        return False

    df_vni = s.to_frame(name="VNINDEX").sort_index().ffill()
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df_vni.to_csv(VNINDEX_DATA)
    logger.info("Đã lưu VNINDEX: %d ngày → %s", len(df_vni), VNINDEX_DATA)
    return True


def update():
    tickers = load_tickers()
    if not tickers:
        logger.error("tickers.csv trống. Thêm mã vào rồi chạy lại.")
        return

    start = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end   = datetime.now().strftime("%Y-%m-%d")
    logger.info("Khoảng thời gian: %s → %s", start, end)

    update_vnindex(start, end)

    # Dữ liệu cổ phiếu chỉ giữ universe equity/ETF, loại VNINDEX khỏi market_data
    stock_tickers = [t for t in tickers if t != "VNINDEX"]
    if not stock_tickers:
        logger.error("Không có ticker cổ phiếu hợp lệ sau khi loại VNINDEX.")
        return

    series_list = []
    failed      = []

    for i, symbol in enumerate(stock_tickers, 1):
        logger.info("[%d/%d] Đang tải %s...", i, len(stock_tickers), symbol)
        s = fetch_close(symbol, start, end)
        if s is not None:
            series_list.append(s)
        else:
            failed.append(symbol)
        time.sleep(1)   # tránh rate limit API

    logger.info("─" * 50)
    logger.info("Thành công: %d / %d mã", len(series_list), len(stock_tickers))

    if failed:
        logger.warning("Bỏ qua %d mã: %s", len(failed), ", ".join(failed))

    if len(series_list) < 2:
        logger.error("Chưa đủ dữ liệu (< 2 mã) — không lưu file.")
        return

    df = pd.concat(series_list, axis=1).sort_index().ffill()
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df.to_csv(MARKET_DATA)
    logger.info("Đã lưu: %d mã × %d ngày → %s", df.shape[1], df.shape[0], MARKET_DATA)


if __name__ == "__main__":
    update()
