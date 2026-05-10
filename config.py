from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR     = Path(__file__).parent
DATA_LAKE    = ROOT_DIR / "data_lake"
MARKET_DATA  = DATA_LAKE / "market_data.csv"
VNINDEX_DATA = DATA_LAKE / "vnindex_cache.csv"
TICKERS_FILE = ROOT_DIR / "tickers.csv"

DATA_LAKE.mkdir(parents=True, exist_ok=True)

VNSTOCK_API_KEY       = os.getenv("VNSTOCK_API_KEY", "")
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
# Key dùng trong UI  ->  {display_name, api_model_name, base_url}
AI_PROVIDER_MAP = {
    "kimi-2.6": {
        "display": "Kimi 2.6",
        "api_model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
    },
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
        "api_model": "deepseek-v4-pro",   # DeepSeek-V3 chat endpoint
        "base_url": "https://api.deepseek.com/v1",
    },
}
