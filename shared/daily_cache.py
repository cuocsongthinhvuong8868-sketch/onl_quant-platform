from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import json
import pickle

from config import DATA_LAKE

CACHE_DIR = DATA_LAKE / "daily_cache"


def _stable_hash(payload_key: dict) -> str:
    raw = json.dumps(payload_key, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cache_file(namespace: str, payload_key: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{namespace}_{_stable_hash(payload_key)}.pkl"


def load_daily_cache(namespace: str, payload_key: dict):
    p = _cache_file(namespace, payload_key)
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            obj = pickle.load(f)
        if obj.get("cache_date") != str(date.today()):
            return None
        return obj.get("payload")
    except Exception:
        return None


def save_daily_cache(namespace: str, payload_key: dict, payload) -> Path:
    p = _cache_file(namespace, payload_key)
    with p.open("wb") as f:
        pickle.dump({"cache_date": str(date.today()), "payload": payload}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return p
