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


def get_cache_path(namespace: str, payload_key: dict) -> Path:
    """Public alias của `_cache_file` để các page truy vấn path mà không dùng underscore."""
    return _cache_file(namespace, payload_key)


def clear_daily_cache(namespace: str, payload_key: dict) -> bool:
    """Xoá file cache cho 1 (namespace, payload_key). Trả True nếu thực sự xoá."""
    p = _cache_file(namespace, payload_key)
    if p.exists():
        p.unlink()
        return True
    return False


def peek_data_date(namespace: str, payload_key: dict) -> str | None:
    """Đọc data_date trong pkl mà không load payload. None nếu pkl không tồn tại
    hoặc file corrupt."""
    p = _cache_file(namespace, payload_key)
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            obj = pickle.load(f)
        return obj.get("data_date")
    except Exception:
        return None


def load_daily_cache(namespace: str, payload_key: dict, data_date: str = None):
    p = _cache_file(namespace, payload_key)
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            obj = pickle.load(f)
        
        # Dùng ngày dữ liệu làm chuẩn, nếu không có thì fallback về ngày hệ thống
        check_date = data_date if data_date else str(date.today())
        
        # Khớp key "data_date" thay vì "cache_date" cũ
        if obj.get("data_date") != check_date:
            return None
            
        return obj.get("payload")
    except Exception:
        return None


def save_daily_cache(namespace: str, payload_key: dict, payload, data_date: str = None) -> Path:
    p = _cache_file(namespace, payload_key)
    save_date = data_date if data_date else str(date.today())
    
    with p.open("wb") as f:
        # Lưu vào key mới "data_date" để ép các file cache cũ (dùng "cache_date") bị vô hiệu hóa
        pickle.dump({"data_date": save_date, "payload": payload}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return p