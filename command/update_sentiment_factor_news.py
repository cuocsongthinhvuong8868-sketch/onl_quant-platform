"""
Update Sentiment Factor From News feed.

Usage:
  python command/update_sentiment_factor_news.py --once
  python command/update_sentiment_factor_news.py --once --source mozyfin
  python command/update_sentiment_factor_news.py --once --source mozyfin_social
"""
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.sentiment_factor_news.engine import main


if __name__ == "__main__":
    main()
