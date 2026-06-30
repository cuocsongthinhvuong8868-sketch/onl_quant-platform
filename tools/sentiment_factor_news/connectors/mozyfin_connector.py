import base64
import html
import json
import logging
import os
import re
import time
from urllib.parse import urljoin

import requests

from tools.sentiment_factor_news.config import (
    DATA_DIR,
    MOZYFIN_ACCESS_TOKEN,
    MOZYFIN_API_BASE,
    MOZYFIN_API_KEY,
    MOZYFIN_AUTH_HEADER,
)

logger = logging.getLogger(__name__)

RESEARCH_NEWS_URL = "https://research.mozyfin.com/news"
TOKEN_CACHE_FILE = DATA_DIR / "mozyfin_token.txt"
DEFAULT_NEXT_ACTION_IDS = (
    "00f0e3d2d4b37aab0e6c8e80c94677d393318a47b7",
    "00de0fef2648a54493cdc0d04f0043907069fbf84d",
)

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://research.mozyfin.com",
    "Referer": RESEARCH_NEWS_URL,
}


def _runtime_access_token() -> str:
    return (
        os.getenv("MOZYFIN_ACCESS_TOKEN")
        or os.getenv("MOZYFIN_TOKEN")
        or MOZYFIN_ACCESS_TOKEN
        or ""
    ).strip()


def _runtime_api_key() -> str:
    return (os.getenv("MOZYFIN_API_KEY") or MOZYFIN_API_KEY or "").strip()


def _runtime_auth_header() -> str:
    return (os.getenv("MOZYFIN_AUTH_HEADER") or MOZYFIN_AUTH_HEADER or "Authorization").strip()


def _get_token_expiry(token_str: str) -> float:
    """Return JWT expiry timestamp, or 0 for opaque/non-JWT tokens."""
    if not token_str:
        return 0
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:]
    parts = token_str.split(".")
    if len(parts) != 3:
        return 0
    try:
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
        return float(payload.get("exp", 0))
    except Exception:
        return 0


def _token_is_fresh(token: str, now: float | None = None) -> bool:
    if not token:
        return False
    exp = _get_token_expiry(token)
    return exp == 0 or exp > (now or time.time()) + 300


def _cookie_header_to_dict(raw_cookie: str) -> dict:
    cookies = {}
    for part in raw_cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def _cookies_to_dict(cookie_data) -> dict:
    if isinstance(cookie_data, dict):
        return {str(k): str(v) for k, v in cookie_data.items() if k and v is not None}

    if isinstance(cookie_data, list):
        cookies = {}
        for item in cookie_data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if name and value is not None:
                cookies[str(name)] = str(value)
        return cookies

    if isinstance(cookie_data, str):
        return _cookie_header_to_dict(cookie_data)

    return {}


def _load_mozyfin_cookies(cookie_file_path: str) -> dict:
    cookie_env = os.getenv("MOZYFIN_COOKIES_JSON", "").strip()
    if cookie_env:
        try:
            cookie_dict = _cookies_to_dict(json.loads(cookie_env))
            if cookie_dict:
                logger.info("Loaded Mozyfin cookies from environment variable.")
                return cookie_dict
        except Exception:
            cookie_dict = _cookie_header_to_dict(cookie_env)
            if cookie_dict:
                logger.info("Loaded Mozyfin cookies from environment cookie header.")
                return cookie_dict
            logger.error("Error parsing MOZYFIN_COOKIES_JSON env.")

    if cookie_file_path and os.path.exists(cookie_file_path):
        try:
            with open(cookie_file_path, "r", encoding="utf-8") as f:
                cookie_dict = _cookies_to_dict(json.load(f))
            if cookie_dict:
                logger.info(f"Loaded Mozyfin cookies from file: {cookie_file_path}")
                return cookie_dict
        except Exception as e:
            logger.error(f"Error reading cookie file {cookie_file_path}: {e}")

    return {}


def _extract_next_action_id(script_text: str) -> str:
    patterns = [
        r'createServerReference\)\("([0-9a-f]{40,})"[^)]*"getLogtoAccess',
        r'"([0-9a-f]{40,})"[^"\n]{0,250}getLogtoAccess',
        r'next-action["\']?\s*[:=]\s*["\']([0-9a-f]{40,})',
        r'createServerReference\)\("([0-9a-f]{40,})"',
    ]
    for pattern in patterns:
        match = re.search(pattern, script_text)
        if match:
            return match.group(1)
    return ""


def _detect_next_action_id() -> str:
    """Detect the current Next.js server action id used to mint Logto access tokens."""
    try:
        response = requests.get(RESEARCH_NEWS_URL, headers=API_HEADERS, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Cannot inspect Mozyfin news page for action id: {response.status_code}")
            return ""

        script_paths = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', response.text, flags=re.I)
        script_urls = [urljoin(RESEARCH_NEWS_URL, html.unescape(path)) for path in script_paths]

        for script_url in script_urls[:40]:
            try:
                script_response = requests.get(script_url, headers=API_HEADERS, timeout=7)
                if script_response.status_code != 200:
                    continue
                action_id = _extract_next_action_id(script_response.text)
                if action_id:
                    logger.info("Detected Mozyfin Next action id from page assets.")
                    return action_id
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Failed to detect Mozyfin Next action id: {e}")
    return ""


def _candidate_next_action_ids() -> list[str]:
    candidates = [
        os.getenv("MOZYFIN_NEXT_ACTION_ID", "").strip(),
        _detect_next_action_id(),
        *DEFAULT_NEXT_ACTION_IDS,
    ]
    seen = set()
    unique = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _refresh_mozyfin_token_via_cookie(cookie_file_path: str) -> str:
    """Refresh Mozyfin access token using authenticated research.mozyfin.com cookies."""
    cookie_dict = _load_mozyfin_cookies(cookie_file_path)
    if not cookie_dict:
        return ""

    for action_id in _candidate_next_action_ids():
        headers = {
            **API_HEADERS,
            "Accept": "text/x-component",
            "next-action": action_id,
        }
        try:
            response = requests.post(
                RESEARCH_NEWS_URL,
                headers=headers,
                cookies=cookie_dict,
                data="[]",
                timeout=15,
            )
            if response.status_code != 200:
                logger.warning(f"Mozyfin token refresh action returned {response.status_code}.")
                continue

            matches = re.findall(
                r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_=]*",
                response.text,
            )
            for token in matches:
                if not _token_is_fresh(token):
                    continue

                os.environ["MOZYFIN_ACCESS_TOKEN"] = token
                try:
                    TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f_out:
                        f_out.write(token)
                except Exception:
                    pass
                logger.info("Refreshed Mozyfin token via cookie.")
                return token
        except Exception as e:
            logger.error(f"Failed to refresh Mozyfin token via cookie: {e}")

    return ""


def _refresh_from_available_cookies() -> str:
    cookie_paths = ["mozyfin_cookies.json", str(DATA_DIR / "mozyfin_cookies.json")]
    for cookie_path in cookie_paths:
        if os.path.exists(cookie_path) or os.getenv("MOZYFIN_COOKIES_JSON"):
            logger.info("Attempting to refresh Mozyfin token via cookie...")
            token = _refresh_mozyfin_token_via_cookie(cookie_path)
            if token:
                return token
    return ""


def _resolve_access_token() -> str:
    now = time.time()

    env_token = _runtime_access_token()
    if _token_is_fresh(env_token, now):
        return env_token

    if TOKEN_CACHE_FILE.exists():
        try:
            cached = TOKEN_CACHE_FILE.read_text(encoding="utf-8").strip()
            if _token_is_fresh(cached, now):
                return cached
        except Exception:
            pass

    refreshed = _refresh_from_available_cookies()
    if refreshed:
        return refreshed

    return env_token


def _build_headers() -> dict:
    headers = dict(API_HEADERS)

    token = _resolve_access_token()
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        return headers

    api_key = _runtime_api_key()
    if api_key:
        auth_header = _runtime_auth_header()
        if auth_header.lower() == "authorization":
            headers["Authorization"] = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
        else:
            headers[auth_header] = api_key

    return headers


def _has_auth(headers: dict) -> bool:
    auth_header = _runtime_auth_header()
    return bool(headers.get("Authorization") or headers.get(auth_header))


def fetch_mozyfin_news(limit: int = 10000) -> list[dict]:
    """
    Fetch raw news from Mozyfin API.
    """
    url = f"{MOZYFIN_API_BASE.rstrip('/')}/news"
    logger.info(f"Fetching mozyfin news with limit={limit}")

    headers = _build_headers()
    if not _has_auth(headers):
        logger.warning(
            "MOZYFIN_ACCESS_TOKEN / MOZYFIN_TOKEN / MOZYFIN_API_KEY / "
            "MOZYFIN_COOKIES_JSON is not configured. Mozyfin now requires "
            "authenticated access for /news, so this source will be skipped."
        )
        return []

    try:
        response = requests.get(
            url,
            headers=headers,
            params={"limit": limit},
            timeout=20,
        )
        if response.status_code == 401:
            logger.warning("Mozyfin API unauthorized; attempting one cookie refresh retry.")
            refreshed = _refresh_from_available_cookies()
            if refreshed:
                retry_headers = dict(API_HEADERS)
                retry_headers["Authorization"] = (
                    refreshed if refreshed.lower().startswith("bearer ") else f"Bearer {refreshed}"
                )
                response = requests.get(url, headers=retry_headers, params={"limit": limit}, timeout=20)

            if response.status_code == 401:
                logger.error(f"Mozyfin API unauthorized. Response: {response.text[:500]}")
                return []

        if response.status_code == 429:
            logger.error("Mozyfin API rate limited with HTTP 429.")
            return []

        response.raise_for_status()
        data = response.json().get("data", [])
        logger.info(f"Successfully fetched {len(data)} items from Mozyfin")
        return data
    except Exception as e:
        logger.error(f"Error fetching Mozyfin news: {e}", exc_info=True)
        return []
