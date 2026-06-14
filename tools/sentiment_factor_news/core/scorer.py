import math
from datetime import datetime, timezone
import logging
from tools.sentiment_factor_news.core.taxonomy import (
    SENTIMENT_LABEL_TO_SCORE,
    IMPORTANT_LEVEL_TO_MAGNITUDE
)

logger = logging.getLogger(__name__)

DEFAULT_RELEVANCE = 0.7
DEFAULT_NOVELTY = 1.0
DEFAULT_SOURCE_WEIGHT = 0.8
DEFAULT_CONFIDENCE = 0.7
DEFAULT_TIME_DECAY = 1.0

SOURCE_WEIGHTS = {
    "widata": 0.85,
    "mozyfin": 0.80,
    "unknown": 0.60,
}

HALF_LIFE_HOURS = {
    "intraday": 6.0,
    "1d_5d": 24.0,
    "1w_1m": 72.0,
    "1m_1q": 168.0,
    "structural": 720.0,
    "unknown": 24.0
}

def calculate_time_decay(timestamp_utc_str: str, horizon: str) -> float:
    """
    Calculate exponential decay based on the publish timestamp and target horizon.
    """
    try:
        # Parse timestamp string like YYYY-MM-DDTHH:MM:SSZ
        # timezone.utc used for timezone-aware comparison
        pub_dt = datetime.fromisoformat(timestamp_utc_str.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        
        delta = now_dt - pub_dt
        hours_old = max(0.0, delta.total_seconds() / 3600.0)
        
        half_life = HALF_LIFE_HOURS.get(horizon, 24.0)
        
        return math.exp(-math.log(2) * hours_old / half_life)
    except Exception as e:
        logger.warning(f"Error calculating time decay for {timestamp_utc_str}: {e}")
        return DEFAULT_TIME_DECAY

def estimate_relevance(item: dict) -> float:
    """Heuristic for determining relevance based on Section 8.5."""
    relevance = 0.6
    if item.get("entities"):
        relevance += 0.1
    if item.get("raw_category") in ["Vĩ mô", "Thị trường"]:
        relevance += 0.1
    if item.get("raw_importance") and item.get("raw_importance") >= 3:
        relevance += 0.1
    macro_info = item.get("macro_info") or {}
    if macro_info.get("title"):
        relevance += 0.1
    return min(relevance, 1.0)

def estimate_confidence(item: dict, matched_rules_count: int) -> float:
    """Heuristic for determining confidence based on Section 8.6."""
    if matched_rules_count >= 2:
        return 0.85
    if matched_rules_count == 1:
        return 0.70
    if item.get("raw_impact") in ["bullish", "bearish", "neutral"]:
        return 0.60
    return 0.40

def score_item(item: dict, classification: dict) -> dict:
    """
    Compute scores for a UnifiedNewsItem using its classification tags.
    Applies the formula:
      final_score = direction_score * magnitude * relevance * novelty * source_weight * confidence * time_decay
    Returns a dictionary of scoring metadata.
    """
    # 1. Direction score
    sentiment_label = classification.get("sentiment_label", "neutral")
    direction_score = SENTIMENT_LABEL_TO_SCORE.get(sentiment_label, 0.0)
    
    # 2. Magnitude
    raw_importance = item.get("raw_importance", 0)
    magnitude = IMPORTANT_LEVEL_TO_MAGNITUDE.get(raw_importance, 1.0)
    
    # 3. Relevance
    relevance = estimate_relevance(item)
    
    # 4. Novelty
    novelty = DEFAULT_NOVELTY # V1 default
    
    # 5. Source weight
    source_system = item.get("source_system", "unknown")
    source_weight = SOURCE_WEIGHTS.get(source_system, 0.60)
    
    # 6. Confidence
    matched_rules_count = classification.get("matched_rules_count", 0)
    confidence = estimate_confidence(item, matched_rules_count)
    
    # 7. Time decay
    horizon = classification.get("horizon", "unknown")
    decay = calculate_time_decay(item.get("timestamp_utc"), horizon)
    
    # Final Score
    final_score = direction_score * magnitude * relevance * novelty * source_weight * confidence * decay
    
    # Round for clean representation
    final_score = round(final_score, 4)
    
    # Return scoring attributes to append to the item
    return {
        "direction_score": direction_score,
        "magnitude": magnitude,
        "relevance": relevance,
        "novelty": novelty,
        "source_weight": source_weight,
        "confidence": confidence,
        "time_decay": round(decay, 4),
        "final_score": final_score
    }
