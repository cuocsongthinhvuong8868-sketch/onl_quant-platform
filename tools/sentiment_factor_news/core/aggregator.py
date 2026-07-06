from datetime import datetime, timezone, timedelta
import logging
import re
from tools.sentiment_factor_news.core.taxonomy import MACRO_CHANNELS
import scipy.stats as stats
import numpy as np

# List of macro abbreviations to not treat as tickers
MACRO_ABBRS = {
    "USD", "VND", "GDP", "PMI", "CPI", "FED", "OMO", "NPL", "DXY", "FDI", 
    "IMF", "WB", "ADB", "SJC", "CNY", "EUR", "JPY", "GBP", "NHNN", "SBV", 
    "BTC", "TPCP", "BCTC", "HOSE", "HNX", "UPCOM", "ON", "BPS", "USA", "US", 
    "UK", "EU", "WTO", "OPEC", "FOMC", "HRC", "PVC", "WTI", "LPR", "API",
    "CNY", "HKD", "AUD", "CAD", "CHF", "SGD", "THB", "MYR", "IDR", "PHP",
    "VND", "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "SEK"
}

# Tickers of major Vietnamese companies to block (starting prefix matching)
COMPANY_TICKERS = {
    "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "STB", "ACB", "SHB", "HDB", 
    "LPB", "TPB", "MSB", "VIB", "EIB", "OCB", "ABB", "PGB", "NCB", "SCB", 
    "NAB", "BAB", "BVB", "SGB", "HPG", "FPT", "MWG", "VIC", "VHM", "VRE", 
    "MSN", "SAB", "VNM", "VJC", "HVN", "NVL", "NLG", "DXG", "PDR", "KDH", 
    "HSG", "NKG", "GEX", "DGC", "DPM", "DCM", "REE", "PLX", "PNJ", "KBC",
    "SSI", "VND"
}

# Specific lowercase company names to check
COMPANY_NAMES = [
    "vietcombank", "bidv", "vietinbank", "techcombank", "vpbank", "mbbank", 
    "sacombank", "agribank", "hdbank", "lienvietpostbank", "lpbank", "tpbank", 
    "seabank", "eximbank", "abbank", "pgbank", "kienlongbank", "vietbank", 
    "saigonbank", "gpbank", "oceanbank", "cbbank", "pvcombank", "dongabank", 
    "baovietbank", "vietcapital", "bản việt", "nam á bank", "namabank",
    "vingroup", "vinhomes", "vincom", "vinfast", "masan", "hòa phát", "hoaphat", 
    "fpt", "thế giới di động", "thegioididong", "petrolimex", "sabeco", "habeco", 
    "vietjet", "vietnam airlines", "novaland", "đất xanh", "phát đạt", "nam long", 
    "khang điền", "hoa sen", "nam kim", "vinamilk", "pv gas", "pv power", "pvpower", 
    "vndirect", "hsc", "vcsc", "vietcap", "mbs", "vps", "flc", "tân hoàng minh", 
    "vạn thịnh phát", "doji", "bảo tín minh châu"
]


logger = logging.getLogger(__name__)

VN_MACRO_WEIGHTS = {
    "liquidity": 0.20,
    "banking_system": 0.175,
    "credit_stress": 0.15,
    "fx_external": 0.125,
    "real_estate_collateral": 0.125,
    "monetary_policy": 0.10,
    "growth": 0.075,
    "fiscal_public_investment": 0.05,
}

def classify_regime(score: float) -> str:
    """
    Classify regime based on adjusted sensitive thresholds for the weighted composite score.
    Reflects the actual statistical variance of the index under normal and extreme conditions.
    """
    if score >= 0.35:
        return "strong_risk_on"
    if score >= 0.15:
        return "risk_on"
    if score > -0.15:
        return "neutral"
    if score > -0.35:
        return "risk_off"
    return "strong_risk_off"


def calculate_channel_scores(items: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    """
    Calculate scores for each channel in MACRO_CHANNELS.
    Using average of final_score for active items.
    Also calculates Bayesian probability of being positive.
    """
    scores = {}
    probs = {}
    channel_items = {channel: [] for channel in MACRO_CHANNELS}
    
    for item in items:
        channel = item.get("macro_channel", "unknown")
        if channel in channel_items:
            channel_items[channel].append(item)
            
    for channel in MACRO_CHANNELS:
        ch_list = channel_items[channel]
        if not ch_list:
            scores[channel] = 0.0
            probs[channel] = 0.5
            continue
            
        active_scores = [i.get("final_score", 0.0) for i in ch_list if abs(i.get("final_score", 0.0)) >= 0.01]
        active_count = len(active_scores)
        total_score = sum(active_scores)
        
        score = total_score / active_count if active_count > 0 else 0.0
        # Apply sensitivity multiplier to map discounted scores back to [-2.0, 2.0] range
        scaled_score = score * 5.0
        # Clamp to [-2.0, 2.0]
        scores[channel] = max(-2.0, min(2.0, round(scaled_score, 4)))
        
        # Bayesian Conjugate Prior update
        if active_count > 0:
            sample_mean = scaled_score
            # Apply Effective Sample Size (ESS) to prevent statistical overconfidence in large windows
            n_eff = np.sqrt(active_count)
            # Prior N(0, 1), Likelihood N(mu, 0.25)
            post_var = 1.0 / (1.0 + (n_eff / 0.25))
            post_mu = post_var * (n_eff * sample_mean / 0.25)
            # Calculate non-directional confidence level: P(sign(mu) == sign(sample_mean))
            prob_pos = stats.norm.cdf(abs(post_mu) / np.sqrt(post_var))
            probs[channel] = round(float(prob_pos), 4)
        else:
            probs[channel] = 0.5
            
    return scores, probs

def build_macro_composite(channel_scores: dict[str, float]) -> float:
    """Calculate composite score based on Vietnam macro weights."""
    composite = 0.0
    for channel, weight in VN_MACRO_WEIGHTS.items():
        composite += channel_scores.get(channel, 0.0) * weight
    return round(composite, 4)

def filter_items_by_window(items: list[dict], minutes: int) -> list[dict]:
    """Filter items published within the last N minutes."""
    filtered = []
    now = datetime.now(timezone.utc)
    
    for item in items:
        try:
            pub_time = datetime.fromisoformat(item["timestamp_utc"].replace("Z", "+00:00"))
            age = now - pub_time
            if age.total_seconds() <= minutes * 60:
                filtered.append(item)
        except Exception as e:
            logger.warning(f"Error parsing date {item.get('timestamp_utc')}: {e}")
            
    return filtered

def build_window_feed(items: list[dict], window_name: str, generated_at_vn: str) -> dict:
    """Build the feed dictionary for a specific window."""
    channel_scores, channel_probs = calculate_channel_scores(items)
    macro_composite = build_macro_composite(channel_scores)
    
    # Calculate composite Bayesian probability
    active_scores = [i.get("final_score", 0.0) for i in items if abs(i.get("final_score", 0.0)) >= 0.01]
    active_count = len(active_scores)
    if active_count > 0:
        sample_mean = macro_composite
        # Apply Effective Sample Size (ESS) to prevent statistical overconfidence
        n_eff = np.sqrt(active_count)
        post_var = 1.0 / (1.0 + (n_eff / 0.25))
        post_mu = post_var * (n_eff * sample_mean / 0.25)
        # Calculate non-directional confidence level: P(sign(mu) == sign(sample_mean))
        composite_prob = float(stats.norm.cdf(abs(post_mu) / np.sqrt(post_var)))
    else:
        composite_prob = 0.5
        
    regime = classify_regime(macro_composite)
    
    # Filter function to exclude company-specific news
    def is_macro_driver(i):
        if i.get("macro_channel") in ["earnings", "unknown", "risk_appetite"]:
            return False
        if i.get("raw_category") == "Doanh nghiệp":
            return False
        if i.get("entities"):
            return False
            
        title = i.get("title", "") or ""
        summary = i.get("summary", "") or ""
        full_text = f"{title} {summary}"
        full_text_lower = full_text.lower()
        
        # Check tags
        for tag in i.get("raw_tags") or []:
            tag_upper = tag.upper()
            tag_lower = tag.lower()
            if tag_upper in COMPANY_TICKERS:
                return False
            if tag_lower in COMPANY_NAMES:
                return False
            for ticker in COMPANY_TICKERS:
                if tag_upper.startswith(ticker) and len(tag_upper) > len(ticker):
                    return False
                    
        # Check COMPANY_NAMES in text
        for cn in COMPANY_NAMES:
            pattern = r'\b' + re.escape(cn) + r'\b'
            if re.search(pattern, full_text_lower):
                return False
                
        # Check tickers prefix in text
        words = re.findall(r'\b[a-zA-Z0-9_]+\b', full_text)
        for w in words:
            w_upper = w.upper()
            for ticker in COMPANY_TICKERS:
                if w_upper.startswith(ticker):
                    if w_upper == ticker:
                        if ticker in ["VND", "GAS", "POW"]:
                            continue
                        else:
                            return False
                    else:
                        return False
                        
        return True

    # Sort positive and negative drivers (excluding company-specific news)
    pos_drivers = [i for i in items if i.get("final_score", 0.0) > 0.0 and is_macro_driver(i)]
    pos_drivers.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
    
    neg_drivers = [i for i in items if i.get("final_score", 0.0) < 0.0 and is_macro_driver(i)]
    neg_drivers.sort(key=lambda x: x.get("final_score", 0.0)) # Most negative first


    
    # Map drivers to standard output format
    def to_driver_format(i):
        return {
            "title": i.get("title"),
            "macro_channel": i.get("macro_channel"),
            "final_score": i.get("final_score"),
            "url": i.get("url"),
            "source": i.get("source_name"),
            "timestamp": i.get("timestamp_vn")
        }
        
    top_pos = [to_driver_format(i) for i in pos_drivers[:5]]
    top_neg = [to_driver_format(i) for i in neg_drivers[:5]]
    
    # Count sources
    mozyfin_count = sum(1 for i in items if i.get("source_system") == "mozyfin")
    widata_count = sum(1 for i in items if i.get("source_system") == "widata")
    
    return {
        "generated_at": generated_at_vn,
        "window": window_name,
        "macro_composite": macro_composite,
        "macro_composite_prob_pos": composite_prob,
        "regime": regime,
        "channel_scores": channel_scores,
        "channel_probs": channel_probs,
        "top_positive_drivers": top_pos,
        "top_negative_drivers": top_neg,
        "news_count": len(items),
        "source_counts": {
            "mozyfin": mozyfin_count,
            "widata": widata_count
        }
    }
