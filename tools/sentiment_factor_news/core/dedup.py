import json
import os
from datetime import datetime, timezone, timedelta
import logging
from tools.sentiment_factor_news.config import HISTORY_FILE, MAX_HISTORY, TIMEZONE

logger = logging.getLogger(__name__)

def load_history() -> dict:
    """Load the unified dedup history file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                # Ensure all required keys exist
                if "seen_source_ids" not in history:
                    history["seen_source_ids"] = []
                if "seen_hashes" not in history:
                    history["seen_hashes"] = []
                return history
        except Exception as e:
            logger.error(f"Error loading dedup history: {e}. Starting fresh.")
            
    return {
        "seen_source_ids": [],
        "seen_hashes": [],
        "updated_at": ""
    }

def save_history(history: dict):
    """Save the updated history back to HISTORY_FILE, maintaining MAX_HISTORY limits."""
    # Enforce history length limit
    history["seen_source_ids"] = history["seen_source_ids"][-MAX_HISTORY:]
    history["seen_hashes"] = history["seen_hashes"][-MAX_HISTORY:]
    
    # Set current time in local timezone
    tz_offset = 7 # Standard VN Time
    vn_tz = timezone(timedelta(hours=tz_offset))
    history["updated_at"] = datetime.now(vn_tz).strftime("%Y-%m-%dT%H:%M:%S+07:00")
    
    try:
        # Create parent dirs if not exist
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving dedup history: {e}")

def dedup_filter(normalized_items: list[dict], history: dict) -> list[dict]:
    """
    Filters out items that have already been processed based on:
    1. news_id (source_system + source_id)
    2. URL (if url is present and not empty)
    3. content_hash (title + url + id + source hash)
    Returns a list of NEW items.
    """
    new_items = []
    seen_ids = set(history["seen_source_ids"])
    seen_hashes = set(history["seen_hashes"])
    
    for item in normalized_items:
        news_id = item["news_id"]
        url = item["url"]
        content_hash = item["content_hash"]
        
        # Check direct id
        if news_id in seen_ids:
            continue
            
        # Check content hash
        if content_hash in seen_hashes:
            continue
            
        # If passed, it's a new item
        new_items.append(item)
        
    return new_items

def update_history_with_items(new_items: list[dict], history: dict) -> dict:
    """
    Updates the history object with the IDs and hashes of newly processed items.
    Does NOT save to disk (call save_history to persist).
    """
    for item in new_items:
        history["seen_source_ids"].append(item["news_id"])
        history["seen_hashes"].append(item["content_hash"])
        
    return history
