import base64
import json
import logging
import os
import re
import time
import requests

from tools.sentiment_factor_news.config import (
    DATA_DIR,
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

TOKEN_CACHE_FILE = DATA_DIR / "mozyfin_token.txt"

def _get_token_expiry(token_str: str) -> float:
    """Giải mã payload của JWT để lấy timestamp hết hạn (exp)."""
    if not token_str:
        return 0
    if token_str.startswith("Bearer "):
        token_str = token_str[7:]
    parts = token_str.split('.')
    if len(parts) != 3:
        return 0
    try:
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        return float(payload.get("exp", 0))
    except Exception:
        return 0

def _refresh_mozyfin_token_via_cookie(cookie_file_path: str) -> str:
    """Gửi Server Action POST làm mới token qua cookie của Mozyfin."""
    cookie_data = None
    
    # 1. Ưu tiên đọc trực tiếp từ biến môi trường của GitHub Actions
    cookie_env = os.getenv("MOZYFIN_COOKIES_JSON")
    if cookie_env:
        try:
            cookie_data = json.loads(cookie_env)
            logger.info("Loaded Mozyfin cookies from environment variable.")
        except Exception as e:
            logger.error(f"Error parsing MOZYFIN_COOKIES_JSON env: {e}")

    # 2. Nếu không có biến môi trường, fallback đọc từ file (local chạy thử)
    if not cookie_data and os.path.exists(cookie_file_path):
        try:
            with open(cookie_file_path, "r", encoding="utf-8") as f:
                cookie_data = json.load(f)
            logger.info(f"Loaded Mozyfin cookies from file: {cookie_file_path}")
        except Exception as e:
            logger.error(f"Error reading cookie file {cookie_file_path}: {e}")

    if not cookie_data:
        return ""

    try:
        cookie_dict = {c["name"]: c["value"] for c in cookie_data}
        
        url = "https://research.mozyfin.com/news"
        headers = {
            "Accept": "text/x-component",
            "next-action": "00de0fef2648a54493cdc0d04f0043907069fbf84d",
        }
        
        r = requests.post(url, headers=headers, cookies=cookie_dict, data="[]", timeout=15)
        if r.status_code == 200:
            matches = re.findall(r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_=]*", r.text)
            if matches:
                token = matches[0]
                
                # Cập nhật cả biến môi trường trong runtime
                os.environ["MOZYFIN_ACCESS_TOKEN"] = token
                
                # Lưu cache cục bộ để tái sử dụng trong phiên chạy (nếu môi trường cho phép ghi file)
                try:
                    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f_out:
                        f_out.write(token)
                except Exception:
                    pass
                return token
    except Exception as e:
        logger.error(f"Failed to refresh Mozyfin token via cookie: {e}")
    return ""

def _build_headers() -> dict:
    headers = dict(API_HEADERS)
    token = ""
    now = time.time()
    
    # Lấy token từ môi trường hiện tại
    env_token = os.getenv("MOZYFIN_ACCESS_TOKEN") or MOZYFIN_ACCESS_TOKEN
    
    # 1. Thử lấy từ config / env hiện tại
    if env_token:
        exp = _get_token_expiry(env_token)
        if exp == 0 or exp > now + 300: # Còn hạn trên 5 phút
            token = env_token
            
    # 2. Thử lấy từ cache file
    if not token and TOKEN_CACHE_FILE.exists():
        try:
            cached = TOKEN_CACHE_FILE.read_text(encoding="utf-8").strip()
            if cached and _get_token_expiry(cached) > now + 300:
                token = cached
        except Exception:
            pass
            
    # 3. Thử refresh qua Cookie nếu cần
    if not token:
        cookie_paths = ["mozyfin_cookies.json", str(DATA_DIR / "mozyfin_cookies.json")]
        for cp in cookie_paths:
            if os.path.exists(cp) or os.getenv("MOZYFIN_COOKIES_JSON"):
                logger.info("Attempting to refresh Mozyfin token via cookie...")
                token = _refresh_mozyfin_token_via_cookie(cp)
                if token:
                    break
                    
    # 4. Fallback cuối cùng
    if not token:
        token = env_token or MOZYFIN_API_KEY
        
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
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

