import logging
import requests

from tools.sentiment_factor_news.config import (
    MOZYFIN_ACCESS_TOKEN,
    MOZYFIN_API_BASE,
    MOZYFIN_API_KEY,
    MOZYFIN_AUTH_HEADER,
)

logger = logging.getLogger(__name__)

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Origin":     "https://research.mozyfin.com",
    "Referer":    "https://research.mozyfin.com/news",
}


def _build_headers() -> dict:
    headers = dict(API_HEADERS)
    if MOZYFIN_ACCESS_TOKEN:
        token = MOZYFIN_ACCESS_TOKEN.strip()
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    elif MOZYFIN_API_KEY:
        key = MOZYFIN_API_KEY.strip()
        if MOZYFIN_AUTH_HEADER.lower() == "authorization":
            headers["Authorization"] = key if key.lower().startswith("bearer ") else f"Bearer {key}"
        else:
            headers[MOZYFIN_AUTH_HEADER] = key
    return headers


def fetch_mozyfin_news(limit: int = 10000) -> list[dict]:
    """
    Fetch raw news from Mozyfin API.
    """
    url = f"{MOZYFIN_API_BASE.rstrip('/')}/news"
    logger.info(f"Fetching mozyfin news with limit={limit}")
    if not (MOZYFIN_ACCESS_TOKEN or MOZYFIN_API_KEY):
        logger.warning(
            "MOZYFIN_ACCESS_TOKEN / MOZYFIN_API_KEY is not configured. Mozyfin now "
            "requires authenticated access for /news, so this source will be skipped."
        )
        return []

    try:
        r = requests.get(
            url,
            headers=_build_headers(),
            params={"limit": limit},
            timeout=20,
        )
        if r.status_code == 401:
            logger.error(f"Mozyfin API unauthorized. Response: {r.text[:500]}")
            return []
        r.raise_for_status()
        data = r.json().get("data", [])
        logger.info(f"Successfully fetched {len(data)} items from Mozyfin")
        return data
    except Exception as e:
        logger.error(f"Error fetching Mozyfin news: {e}", exc_info=True)
        return []

