import time
import random
import hashlib
import requests
import logging
from tools.sentiment_factor_news.config import WIDATA_SIGN_TOKEN

logger = logging.getLogger(__name__)

API_BASE = "https://wichart.vn/wichartapi"
REFERER = "https://widata.vn/"

def _get_signed_headers(params: dict) -> dict:
    """Tạo header có chữ ký MD5 theo chuẩn WiChart."""
    auth = {
        "stime":      int(time.time() * 1000),
        "nonce":      str(random.randint(10**19, 10**20 - 1)),
        "sign-token": WIDATA_SIGN_TOKEN,
        "v":          "v1",
    }
    sign_source = {**params, **auth}
    sign_text = "".join(
        k + str(sign_source[k])
        for k in sorted(sign_source)
        if k != "sign"
    )
    auth["sign"] = hashlib.md5(sign_text.encode("utf-8")).hexdigest()

    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Origin":     "https://widata.vn",
        "Referer":    REFERER,
        "Accept":     "application/json, text/plain, */*",
        **{k: str(v) for k, v in auth.items()},
    }

def fetch_widata_signals(limit: int = 1000) -> list[dict]:
    """
    Fetch raw signals from WiData API.
    Paginates through pages if limit is larger than 100 to get full history.
    """
    if not WIDATA_SIGN_TOKEN:
        logger.warning("WIDATA_SIGN_TOKEN is not configured. Skipping WiData fetch.")
        return []

    url = f"{API_BASE}/xbrain-news/"
    all_signals = []
    page = 1
    limit_per_page = 100 if limit > 100 else limit
    
    logger.info(f"Fetching WiData signals with total limit target={limit}")
    
    while len(all_signals) < limit:
        remaining = limit - len(all_signals)
        current_limit = min(limit_per_page, remaining)
        
        params = {
            "page":  str(page),
            "limit": str(current_limit),
        }
        
        try:
            headers = _get_signed_headers(params)
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                logger.error(f"WiData API returned failure on page {page}: {data.get('message')}")
                break
            
            signals = data.get("data", [])
            if not signals:
                break
                
            all_signals.extend(signals)
            logger.info(f"Page {page}: Fetched {len(signals)} signals. Accumulated total: {len(all_signals)}")
            
            # If we fetched fewer items than requested, we reached the end
            if len(signals) < current_limit:
                break
                
            page += 1
            time.sleep(0.3) # Avoid rate limits
        except Exception as e:
            logger.error(f"Error fetching WiData signals on page {page}: {e}", exc_info=True)
            break
            
    logger.info(f"Successfully fetched {len(all_signals)} total signals from WiData")
    return all_signals
