"""
shared/data_loader.py
Đọc dữ liệu từ data_lake — không gọi API trực tiếp.
"""
import logging
import pandas as pd
from pathlib import Path
from config import MARKET_DATA, MARKET_VOLUME, DATA_LAKE

logger = logging.getLogger(__name__)


def load_close_prices() -> pd.DataFrame:
    """
    Tải giá đóng cửa từ data_lake/market_data.csv.
    index = ngày, columns = mã cổ phiếu.

    Raises
    ------
    FileNotFoundError nếu chưa chạy update_data.py.
    """
    if not MARKET_DATA.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {MARKET_DATA}.\n"
            "Vui lòng chạy: python update_data.py"
        )
    df = pd.read_csv(MARKET_DATA, index_col=0, parse_dates=True)
    logger.info("Đã tải market_data: %d ngày × %d mã", *df.shape)
    return df


def load_volumes() -> pd.DataFrame | None:
    """Tải khối lượng từ data_lake/market_volume.csv.

    Trả về None nếu file chưa tồn tại — caller (vd. ESR Monitor) phải fallback
    sang volume proxy với cảnh báo. Sau khi user chạy lại update_data.py với
    bản đã sửa A1, file sẽ có sẵn.

    Columns trùng với load_close_prices() (cùng tickers). Volume có thể có NaN
    cho ngày không giao dịch — caller xử lý NaN tuỳ ngữ cảnh.
    """
    if not MARKET_VOLUME.exists():
        logger.warning(
            "market_volume.csv chưa tồn tại. Chạy `python command/update_data.py "
            "--backfill 2190` để fetch lại lịch sử có volume."
        )
        return None
    df = pd.read_csv(MARKET_VOLUME, index_col=0, parse_dates=True)
    logger.info("Đã tải market_volume: %d ngày × %d mã", *df.shape)
    return df


def load_custom(filename: str) -> pd.DataFrame:
    """Tải file bất kỳ từ data_lake theo tên file."""
    path = DATA_LAKE / filename
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path} trong data_lake.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    logger.info("Đã tải %s: %d rows × %d cols", filename, *df.shape)
    return df


def load_ticker_metadata() -> pd.DataFrame | None:
    """Tải ticker_metadata.csv (ICB sector + exchange).

    Cào bằng `python command/update_sector_data.py`. Index=Ticker,
    cols=[industry_code, industry_name, exchange].

    Trả về None nếu file chưa tồn tại — caller phải fallback gracefully.
    """
    path = DATA_LAKE / "ticker_metadata.csv"
    if not path.exists():
        logger.warning(
            "ticker_metadata.csv chưa tồn tại. Chạy `python command/update_sector_data.py` để cào."
        )
        return None
    df = pd.read_csv(path, index_col=0)
    logger.info("Đã tải ticker_metadata: %d rows × %d cols", *df.shape)
    return df
