import requests
import logging

logger = logging.getLogger(__name__)

API_BASE = "https://api.antofin.com/api/v1"
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Origin":     "https://research.mozyfin.com",
    "Referer":    "https://research.mozyfin.com/news",
}

def fetch_mozyfin_news(limit: int = 10000) -> list[dict]:
    """
    Fetch raw news from Mozyfin API.
    """
    url = f"{API_BASE}/news"
    logger.info(f"Fetching mozyfin news with limit={limit}")
    try:
        r = requests.get(
            url,
            headers=API_HEADERS,
            params={"limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        logger.info(f"Successfully fetched {len(data)} items from Mozyfin")
        return data
    except Exception as e:
        logger.error(f"Error fetching Mozyfin news: {e}", exc_info=True)
        return []

