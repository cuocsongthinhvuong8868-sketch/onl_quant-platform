"""
shared/data_loader.py
Đọc dữ liệu từ data_lake — không gọi API trực tiếp.
"""
import logging
import pandas as pd
from pathlib import Path
from config import MARKET_DATA, DATA_LAKE

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


def load_custom(filename: str) -> pd.DataFrame:
    """Tải file bất kỳ từ data_lake theo tên file."""
    path = DATA_LAKE / filename
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path} trong data_lake.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    logger.info("Đã tải %s: %d rows × %d cols", filename, *df.shape)
    return df
