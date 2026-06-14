import logging
from tools.sentiment_factor_news.core.taxonomy import (
    MACRO_CHANNELS,
    MOZYFIN_SECTOR_TO_CHANNEL,
    MOZYFIN_TOPIC_TO_CHANNEL,
    WIDATA_TAG_TO_CHANNEL,
    LIQUIDITY_KEYWORDS,
    FX_KEYWORDS,
    CREDIT_STRESS_KEYWORDS,
    REAL_ESTATE_KEYWORDS,
    BANKING_KEYWORDS,
    EVENT_TRANSMISSION,
    EVENT_HORIZON
)

logger = logging.getLogger(__name__)

# Keywords associated with macro channels for fallback classification
CHANNEL_KEYWORDS = {
    "growth": ["gdp", "pmi", "tăng trưởng", "phục hồi", "sản xuất", "bán lẻ", "iip", "xuất khẩu", "nhập khẩu", "kinh tế"],
    "inflation": ["cpi", "lạm phát", "giá tiêu dùng", "giá cả"],
    "monetary_policy": ["lãi suất", "sbv", "ngân hàng nhà nước", "chính sách tiền tệ", "điều hành", "nhnn", "fed"],
    "liquidity": ["omo", "tín phiếu", "bơm ròng", "hút ròng", "bơm tiền", "hút tiền", "liên ngân hàng", "thanh khoản", "margin", "call margin", "giải chấp"],
    "credit_stress": ["trái phiếu", "nợ xấu", "chậm trả", "vỡ nợ", "gia hạn nợ", "tái cơ cấu", "default", "npl"],
    "fx_external": ["tỷ giá", "usd/vnd", "dxy", "ngoại hối", "bán ngoại tệ", "khối ngoại", "fdi", "kiều hối"],
    "fiscal_public_investment": ["đầu tư công", "ngân sách", "giải ngân", "cao tốc", "dự án công"],
    "real_estate_collateral": ["bất động sản", "nhà đất", "dự án pháp lý", "phân khúc", "thị trường bất động sản", "quy hoạch"],
    "banking_system": ["ngân hàng", "tín dụng", "casa", "nim", "car", "trích lập", "lãi ròng", "huy động", "ldr"],
    "risk_appetite": ["chứng khoán", "vn-index", "vnindex", "thị trường chứng khoán", "cổ phiếu", "ipo", "niêm yết"],
    "earnings": ["kết quả kinh doanh", "lợi nhuận", "doanh thu", "báo cáo tài chính", "lãi", "lỗ"],
    "commodity": ["dầu khí", "giá dầu", "hàng hóa", "thép", "kim loại", "lúa gạo", "nông sản", "cao su"]
}

# Positive vs Negative sentiment words in Vietnamese news
SENTIMENT_KEYWORDS = {
    "positive": [
        "tăng", "vượt", "cải thiện", "phục hồi", "tháo gỡ", "hỗ trợ", "nới lỏng", 
        "bơm ròng", "bơm tiền", "ổn định", "mua ròng", "cắt giảm lãi suất", 
        "giảm lãi suất", "thu hút", "đạt", "lãi", "tăng trưởng", "khởi sắc"
    ],
    "negative": [
        "giảm", "sụt giảm", "yếu", "áp lực", "căng thẳng", "chậm trả", "vỡ nợ", 
        "nợ xấu", "default", "npl", "hút ròng", "hút tiền", "rút vốn", "bán ròng", 
        "mất giá", "lỗ", "lo ngại", "bất ổn", "rủi ro", "thắt chặt", "spike", "tăng tỷ giá"
    ]
}

def classify_macro_channel(item: dict) -> str:
    """
    Classifies a UnifiedNewsItem into a macro channel.
    Rules:
    1. Mozyfin: Sectors first, then topics.
    2. WiData: Tags first, then category.
    3. Fallback to keyword matching in title/summary.
    """
    source_system = item.get("source_system")
    
    # 1. Mozyfin logic
    if source_system == "mozyfin":
        # Check sectors
        for sector in (item.get("sectors") or []):
            if sector in MOZYFIN_SECTOR_TO_CHANNEL:
                return MOZYFIN_SECTOR_TO_CHANNEL[sector]
        # Check topics
        for topic in (item.get("raw_topics") or []):
            if topic in MOZYFIN_TOPIC_TO_CHANNEL:
                return MOZYFIN_TOPIC_TO_CHANNEL[topic]
                
    # 2. WiData logic
    elif source_system == "widata":
        # Check tags
        for tag in (item.get("raw_tags") or []):
            if tag in WIDATA_TAG_TO_CHANNEL:
                return WIDATA_TAG_TO_CHANNEL[tag]
        # Check category
        cat = item.get("raw_category")
        if cat:
            if "vĩ mô" in cat.lower():
                # Fallback to keyword search for specific macro channels, but default to growth/monetary if none
                pass
            elif "thị trường" in cat.lower():
                return "risk_appetite"
            elif "doanh nghiệp" in cat.lower():
                return "earnings"
            elif "hàng hóa" in cat.lower():
                return "commodity"
                
    # 3. Fallback keyword search on Title + Summary
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    
    # Check for exact matches first
    matched_channels = {}
    for channel, kw_list in CHANNEL_KEYWORDS.items():
        score = 0
        for kw in kw_list:
            if kw in text:
                # Give more weight to matches in title
                if kw in item.get('title', '').lower():
                    score += 2
                else:
                    score += 1
        if score > 0:
            matched_channels[channel] = score
            
    if matched_channels:
        # Return the channel with highest match score
        return max(matched_channels, key=matched_channels.get)
        
    return "unknown"

def classify_event_type(item: dict, macro_channel: str) -> str:
    """
    Search keywords corresponding to the macro channel to identify specific events.
    """
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    
    keywords_map = {}
    if macro_channel == "liquidity":
        keywords_map = LIQUIDITY_KEYWORDS
    elif macro_channel == "fx_external":
        keywords_map = FX_KEYWORDS
    elif macro_channel == "credit_stress":
        keywords_map = CREDIT_STRESS_KEYWORDS
    elif macro_channel == "real_estate_collateral":
        keywords_map = REAL_ESTATE_KEYWORDS
    elif macro_channel == "banking_system":
        keywords_map = BANKING_KEYWORDS
        
    for event_name, kw_list in keywords_map.items():
        for kw in kw_list:
            if kw in text:
                return event_name
                
    # Return generic event type if no specific matches
    return f"{macro_channel}_generic"

def infer_transmission(event_type: str, macro_channel: str, sentiment: str = "neutral") -> list[str]:
    """
    Get the transmission channels affected by the event.
    """
    if event_type in EVENT_TRANSMISSION:
        return EVENT_TRANSMISSION[event_type]
        
    # Default fallback transmission based on channel and sentiment
    if macro_channel == "risk_appetite":
        return ["risk_on"] if sentiment in ["positive", "very_positive"] else ["risk_off"]
    elif macro_channel == "liquidity":
        return ["liquidity_easing"] if sentiment in ["positive", "very_positive"] else ["liquidity_tightening"]
    elif macro_channel == "monetary_policy":
        return ["liquidity_easing"] if sentiment in ["positive", "very_positive"] else ["liquidity_tightening"]
    elif macro_channel == "credit_stress":
        return ["credit_easing"] if sentiment in ["positive", "very_positive"] else ["credit_tightening"]
    elif macro_channel == "growth":
        return ["growth_upgrade"] if sentiment in ["positive", "very_positive"] else ["growth_downgrade"]
    elif macro_channel == "inflation":
        return ["disinflation_support"] if sentiment in ["positive", "very_positive"] else ["inflation_pressure"]
        
    return []

def infer_horizon(event_type: str, macro_channel: str) -> str:
    """
    Determine the target horizon for the market impact.
    """
    if event_type in EVENT_HORIZON:
        return EVENT_HORIZON[event_type]
        
    # Fallback based on channel
    channel_horizons = {
        "monetary_policy": "1m_1q",
        "liquidity": "1d_5d",
        "growth": "1m_1q",
        "inflation": "1m_1q",
        "fx_external": "1w_1m",
        "credit_stress": "1m_1q",
        "real_estate_collateral": "1q_1y",
        "banking_system": "1m_1q",
        "risk_appetite": "1d_5d",
        "earnings": "1m_1q",
        "commodity": "1w_1m"
    }
    return channel_horizons.get(macro_channel, "unknown")

def classify_sentiment(item: dict, event_type: str) -> str:
    """
    Classify the sentiment label of the UnifiedNewsItem.
    Returns: very_positive | positive | neutral | negative | very_negative | unknown
    """
    # If there is a raw impact, use it first
    raw_impact = item.get("raw_impact")
    if raw_impact:
        if raw_impact == "bullish":
            return "positive"
        elif raw_impact == "bearish":
            return "negative"
        elif raw_impact == "neutral":
            return "neutral"
            
    # Check if event type implies a direction
    event_sentiment_priors = {
        "sbv_injection": "positive",
        "vnd_stabilization": "positive",
        "dxy_fall": "positive",
        "fed_dovish": "positive",
        "foreign_inflow": "positive",
        "legal_easing": "positive",
        "presales_recovery": "positive",
        "mortgage_easing": "positive",
        "nim_expansion": "positive",
        "casa_recovery": "positive",
        "car_improvement": "positive",
        "interbank_rate_decline": "positive",
        "deposit_rate_decline": "positive",
        
        "sbv_withdrawal": "negative",
        "interbank_rate_spike": "negative",
        "deposit_rate_increase": "negative",
        "margin_call_pressure": "negative",
        "vnd_depreciation": "negative",
        "dxy_rise": "negative",
        "fed_hawkish": "negative",
        "foreign_outflow": "negative",
        "npl_increase": "negative",
        "bond_default": "very_negative",
        "bond_restructuring": "negative",
        "credit_downgrade": "negative",
        "counterparty_stress": "negative",
        "inventory_pressure": "negative",
        "developer_default": "very_negative",
        "property_price_decline": "negative",
        "nim_compression": "negative",
        "npl_pressure": "negative",
        "funding_stress": "negative"
    }
    
    if event_type in event_sentiment_priors:
        return event_sentiment_priors[event_type]
        
    # Heuristic: Count sentiment keywords in text
    title_summary = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    
    pos_score = sum(1 for kw in SENTIMENT_KEYWORDS["positive"] if kw in title_summary)
    neg_score = sum(1 for kw in SENTIMENT_KEYWORDS["negative"] if kw in title_summary)
    
    # Adjust score: words in title have higher weight
    title_lower = item.get('title', '').lower()
    pos_score += sum(1 for kw in SENTIMENT_KEYWORDS["positive"] if kw in title_lower)
    neg_score += sum(1 for kw in SENTIMENT_KEYWORDS["negative"] if kw in title_lower)
    
    if pos_score > neg_score:
        return "very_positive" if (pos_score - neg_score) >= 3 else "positive"
    elif neg_score > pos_score:
        return "very_negative" if (neg_score - pos_score) >= 3 else "negative"
        
    return "neutral"

def classify_and_tag_item(item: dict) -> dict:
    """
    Main entrypoint to classify and add tags to a UnifiedNewsItem dictionary.
    Returns the ClassifiedNewsItem fields merged with the input item.
    """
    macro_channel = classify_macro_channel(item)
    event_type = classify_event_type(item, macro_channel)
    sentiment_label = classify_sentiment(item, event_type)
    
    transmission = infer_transmission(event_type, macro_channel, sentiment_label)
    horizon = infer_horizon(event_type, macro_channel)
    
    # Calculate rule match count for confidence estimation
    matched_rules_count = 0
    if event_type != f"{macro_channel}_generic":
        matched_rules_count += 1
    if macro_channel != "unknown":
        matched_rules_count += 1
        
    classification = {
        "macro_channel": macro_channel,
        "sub_channel": event_type, # mapping sub_channel to event_type
        "event_type": event_type,
        "sentiment_label": sentiment_label,
        "market_transmission": transmission,
        "horizon": horizon,
        "matched_rules_count": matched_rules_count
    }
    
    return classification
