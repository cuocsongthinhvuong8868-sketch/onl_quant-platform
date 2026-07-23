"""
command/update_vnibor.py — Updater VietNam VNIBOR.
Kéo lãi suất liên ngân hàng từ WiChart API và lưu vào data_lake/LaiSuatLienNganHang_Wichart.csv.
"""
import requests
import datetime
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_LAKE  # noqa: E402


VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def _timestamp_ms_to_vietnam_date(timestamp_ms: int | float) -> str:
    timestamp_utc = datetime.datetime.fromtimestamp(
        float(timestamp_ms) / 1000.0,
        datetime.timezone.utc,
    )
    return timestamp_utc.astimezone(VIETNAM_TIMEZONE).strftime("%Y-%m-%d")

def update_vnibor():
    url = "https://api.wichart.vn/vietnambiz/vi-mo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://data.vietnambiz.vn",
        "Referer": "https://data.vietnambiz.vn/"
    }
    params = {
        "name": "lslnh",
        "type": "d"
    }

    logger.info("Đang gọi WiChart API lấy lãi suất liên ngân hàng...")
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
    except Exception as e:
        logger.error(f"Lỗi kết nối API: {e}")
        return False

    if response.status_code != 200:
        logger.error(f"WiChart API trả về mã lỗi: {response.status_code}")
        return False

    data = response.json()
    series_list = data.get("chart", {}).get("series", [])
    
    data_by_date = {}
    series_mapping = {
        "LS qua đêm liên ngân hàng": "Overnight_ON",
        "LS liên ngân hàng kỳ hạn 1 tuần": "1_Week",
        "LS liên ngân hàng kỳ hạn 2 tuần": "2_Weeks"
    }

    for series in series_list:
        original_name = series.get("name")
        mapped_name = series_mapping.get(original_name, original_name)
        data_points = series.get("data", [])
        
        for pts in data_points:
            if len(pts) < 2:
                continue
            ts_ms, val = pts[0], pts[1]
            if val is None:
                continue
                
            date_str = _timestamp_ms_to_vietnam_date(ts_ms)
            
            if date_str not in data_by_date:
                data_by_date[date_str] = {}
            data_by_date[date_str][mapped_name] = val

    sorted_dates = sorted(data_by_date.keys(), reverse=True)
    if not sorted_dates:
        logger.warning("Không tìm thấy dữ liệu lãi suất nào từ API.")
        return False

    csv_path = DATA_LAKE / "LaiSuatLienNganHang_Wichart.csv"
    logger.info(f"Đang ghi {len(sorted_dates)} hàng dữ liệu vào {csv_path}...")
    
    try:
        DATA_LAKE.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8-sig") as csv_file:
            csv_file.write("Ngày,Lãi suất qua đêm _ON (%),Lãi suất 1 tuần (%),Lãi suất 2 tuần (%)\n")
            for date in sorted_dates:
                row_data = data_by_date[date]
                on_val = row_data.get("Overnight_ON", "")
                w1_val = row_data.get("1_Week", "")
                w2_val = row_data.get("2_Weeks", "")
                csv_file.write(f"{date},{on_val},{w1_val},{w2_val}\n")
        logger.info("Cập nhật dữ liệu VNIBOR thành công!")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi ghi file: {e}")
        return False

if __name__ == "__main__":
    update_vnibor()
