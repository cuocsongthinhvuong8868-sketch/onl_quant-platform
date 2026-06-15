from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR            = Path(__file__).parent
DATA_LAKE           = ROOT_DIR / "data_lake"
MARKET_DATA         = DATA_LAKE / "market_data.csv"
MARKET_VOLUME       = DATA_LAKE / "market_volume.csv"      # khớp shape MARKET_DATA, lưu volume
VNINDEX_DATA        = DATA_LAKE / "vnindex_cache.csv"
VN30_DATA           = DATA_LAKE / "vn30_cache.csv"          # nay chứa cả VN30 + VN30_volume nếu có
FED_LIQUIDITY_DATA  = DATA_LAKE / "fed_liquidity_cache.csv"
TICKERS_FILE        = ROOT_DIR / "tickers.csv"

DATA_LAKE.mkdir(parents=True, exist_ok=True)

VNSTOCK_API_KEY       = os.getenv("VNSTOCK_API_KEY", "")
FRED_API_KEY          = os.getenv("FRED_API_KEY", "")
DEFAULT_LOOKBACK_DAYS = 1095      # ~3 năm — dùng khi file chưa tồn tại
DEFAULT_BACKFILL_DAYS = 2190      # ~6 năm — gợi ý cho --backfill
DEFAULT_WINDOW        = 60
RANK_WINDOW           = 252

SCORE_BANDS = [
    (0,  20, "rgba(220, 50,  50,  0.2)", "EXTREME FEAR"),
    (20, 40, "rgba(255, 165, 0,   0.2)", "FEAR"),
    (40, 60, "rgba(180, 180, 180, 0.2)", "STOCK PICKING"),
    (60, 80, "rgba(173, 255, 47,  0.2)", "GREED"),
    (80,100, "rgba(0,   180, 0,   0.2)", "EXTREME GREED"),
]

# ── AI Model Configuration ──
# Đổi model / temperature tại đây — tất cả tools sẽ đọc từ đây
AI_MODEL       = os.getenv("AI_MODEL", "kimi-k2.6")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "1.0"))

# ── Multi-provider AI map ──
# Key dùng trong UI  ->  {display_name, api_model_name, base_url, temperature}
AI_PROVIDER_MAP = {
    "kimi-2.6": {
        "display": "Kimi 2.6",
        "api_model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
        "temperature": 1.0,
    },
    "kimi-2.6-local": {
        "display": "Kimi 2.6 Local",
        "api_model": os.getenv("KIMI_LOCAL_MODEL", "kimi-k2.6"),
        "base_url": os.getenv("KIMI_LOCAL_BASE_URL", "http://127.0.0.1:5001/v1"),
        "temperature": float(os.getenv("KIMI_LOCAL_TEMPERATURE", "0.4")),
        "timeout": float(os.getenv("KIMI_LOCAL_TIMEOUT", "600")),
    },
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
        "api_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "temperature": 0.5,
    },
}
