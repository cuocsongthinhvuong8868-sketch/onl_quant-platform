import os
from pathlib import Path
from dotenv import load_dotenv

from config import DATA_LAKE, ROOT_DIR

# Load env variables from .env if present
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = DATA_LAKE / "sentiment_factor_news"
LOGS_DIR = DATA_DIR / "logs"

# Ensure dirs exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
(DATA_DIR / "raw").mkdir(exist_ok=True)
(DATA_DIR / "normalized").mkdir(exist_ok=True)
(DATA_DIR / "classified").mkdir(exist_ok=True)
(DATA_DIR / "feed").mkdir(exist_ok=True)
(DATA_DIR / "history").mkdir(exist_ok=True)

# WiData / WiChart settings
WIDATA_SIGN_TOKEN = os.getenv("WIDATA_SIGN_TOKEN", "")

# Git publisher settings
FEED_REPO_PATH = os.getenv("FEED_REPO_PATH", str(ROOT_DIR))
GIT_REMOTE_NAME = os.getenv("GIT_REMOTE_NAME", "origin")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_COMMIT_AUTHOR_NAME = os.getenv("GIT_COMMIT_AUTHOR_NAME", "market-sentiment-bot")
GIT_COMMIT_AUTHOR_EMAIL = os.getenv("GIT_COMMIT_AUTHOR_EMAIL", "bot@example.com")

# Runtime settings
FETCH_LIMIT_MOZYFIN = int(os.getenv("FETCH_LIMIT_MOZYFIN", "100"))
FETCH_LIMIT_WIDATA = int(os.getenv("FETCH_LIMIT_WIDATA", "50"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
RUN_WINDOW_MINUTES = int(os.getenv("RUN_WINDOW_MINUTES", "30"))
PORT = int(os.getenv("PORT", "8000"))

# History configuration
HISTORY_FILE = DATA_DIR / "history" / "processed_news_ids.json"
MAX_HISTORY = 5000
