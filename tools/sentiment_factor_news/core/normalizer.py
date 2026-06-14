import html
import hashlib
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """Decode HTML entities and trim whitespace."""
    if not text:
        return ""
    # Ensure it is a string
    text_str = str(text)
    return html.unescape(text_str).strip()

def parse_and_format_dates(date_str: str) -> tuple[str, str]:
    """
    Parse an ISO date string and return:
    (timestamp_utc, timestamp_vn) in ISO formats.
    Defaulting to current time if parsing fails.
    """
    if not date_str:
        dt = datetime.now(timezone.utc)
    else:
        try:
            # Replace Z with +00:00 for fromisoformat compatibility in older python versions
            clean_str = date_str.replace("Z", "+00:00")
            # Handle fractional seconds if any, e.g. .000
            # fromisoformat handles +00:00 offset well in Python 3.7+
            dt = datetime.fromisoformat(clean_str)
        except Exception as e:
            logger.warning(f"Could not parse date string: {date_str}, error: {e}")
            dt = datetime.now(timezone.utc)
            
    # Ensure dt is timezone-aware and in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
        
    # Format UTC
    timestamp_utc = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Convert and format VN time (+07:00)
    vn_tz = timezone(timedelta(hours=7))
    dt_vn = dt.astimezone(vn_tz)
    timestamp_vn = dt_vn.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    
    return timestamp_utc, timestamp_vn

def generate_content_hash(source_system: str, source_id: str, url: str, title: str) -> str:
    """Generate content hash based on Section 9.1."""
    hash_input = f"{source_system}|{source_id}|{url}|{title}".lower().strip()
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

def normalize_mozyfin(item: dict) -> dict:
    """Normalize a raw Mozyfin news item to UnifiedNewsItem schema."""
    source_id = str(item.get("id", ""))
    title = clean_text(item.get("title", ""))
    summary = clean_text(item.get("vi_summary") or item.get("summary") or "")
    url = item.get("url", "")
    
    timestamp_utc, timestamp_vn = parse_and_format_dates(item.get("published_date"))
    
    # Extract entities and sectors
    entities = [str(e).upper().strip() for e in (item.get("entities") or []) if e]
    sectors = [str(s).strip() for s in (item.get("sectors") or []) if s]
    
    raw_topics = [str(t).strip() for t in (item.get("key_topics") or []) if t]
    raw_impact = item.get("market_impact")
    if raw_impact:
        raw_impact = str(raw_impact).lower().strip()
        if raw_impact not in ["bullish", "bearish", "neutral"]:
            raw_impact = "neutral"
            
    content_hash = generate_content_hash("mozyfin", source_id, url, title)
    
    return {
        "news_id": f"mozyfin_{source_id}",
        "source_system": "mozyfin",
        "source_id": source_id,
        "timestamp_utc": timestamp_utc,
        "timestamp_vn": timestamp_vn,
        "source_name": clean_text(item.get("source") or "Mozyfin"),
        "title": title,
        "summary": summary,
        "url": url,
        "language": "vi",  # Default to Vietnamese since Mozyfin is mostly VI
        "raw_category": None,
        "raw_tags": [],
        "raw_topics": raw_topics,
        "raw_impact": raw_impact,
        "raw_importance": 0,
        "entities": entities,
        "sectors": sectors,
        "country": "Vietnam",
        "macro_info": {
            "title": None,
            "value": None,
            "prev_value": None,
            "unit": None
        },
        "content_hash": content_hash
    }

def normalize_widata(item: dict) -> dict:
    """Normalize a raw WiData signal item to UnifiedNewsItem schema."""
    source_id = str(item.get("id", ""))
    title = clean_text(item.get("ai_translated_title") or item.get("title") or "")
    summary = clean_text(item.get("ai_summary") or item.get("main_content_text") or item.get("content") or "")
    url = item.get("url") or item.get("url_news") or ""
    
    timestamp_utc, timestamp_vn = parse_and_format_dates(item.get("publish_date") or item.get("published_date"))
    
    # Combine tags
    raw_tags = []
    for tag_field in ["tag_level_0", "tag_level_1", "tag_level_2"]:
        val = item.get(tag_field)
        if isinstance(val, list):
            raw_tags.extend([str(t).strip() for t in val if t])
        elif val:
            raw_tags.append(str(val).strip())
            
    # Extract entities from code_info list
    entities = []
    code_info = item.get("code_info") or []
    if isinstance(code_info, list):
        for c in code_info:
            if isinstance(c, dict) and c.get("code"):
                entities.append(str(c["code"]).upper().strip())
                
    # Raw importance level
    raw_importance = item.get("important_level")
    metadata = item.get("metadata")
    if metadata and isinstance(metadata, dict):
        raw_importance = metadata.get("important_level", raw_importance)
        
    try:
        raw_importance = int(raw_importance) if raw_importance is not None else 0
    except (ValueError, TypeError):
        raw_importance = 0
        
    # Extract macro info
    macro = item.get("macro_info") or {}
    macro_info = {
        "title": macro.get("title") if macro.get("title") else None,
        "value": macro.get("value") if macro.get("value") is not None else None,
        "prev_value": macro.get("prev_value") if macro.get("prev_value") is not None else None,
        "unit": macro.get("unit") if macro.get("unit") else None
    }
    
    content_hash = generate_content_hash("widata", source_id, url, title)
    
    return {
        "news_id": f"widata_{source_id}",
        "source_system": "widata",
        "source_id": source_id,
        "timestamp_utc": timestamp_utc,
        "timestamp_vn": timestamp_vn,
        "source_name": clean_text(item.get("source") or "WiData"),
        "title": title,
        "summary": summary,
        "url": url,
        "language": "vi",  # Mostly Vietnamese
        "raw_category": clean_text(item.get("category")),
        "raw_tags": raw_tags,
        "raw_topics": [],
        "raw_impact": None, # Will be determined by classifier
        "raw_importance": raw_importance,
        "entities": entities,
        "sectors": [],
        "country": clean_text(item.get("country") or "Vietnam"),
        "macro_info": macro_info,
        "content_hash": content_hash
    }

def normalize_item(item: dict, source_system: str) -> dict:
    """Normalize a raw dictionary to UnifiedNewsItem depending on source."""
    if source_system == "mozyfin":
        return normalize_mozyfin(item)
    elif source_system == "widata":
        return normalize_widata(item)
    else:
        raise ValueError(f"Unknown source system: {source_system}")
