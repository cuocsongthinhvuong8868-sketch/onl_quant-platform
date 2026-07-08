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

SENTIMENT_SCORE_SCALE = 5.0
BAYES_PRIOR_MEAN = 0.0
BAYES_PRIOR_SD = 1.0
BAYES_BASE_SIGMA = 0.5
BAYES_RELIABILITY_FLOOR = 0.05
ACTIVE_SCORE_THRESHOLD = 0.01

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


def _safe_float(value, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if not np.isfinite(out):
        return default
    return out


def _item_reliability(item: dict) -> float:
    source_weight = _safe_float(item.get("source_weight"), 0.8)
    confidence = _safe_float(item.get("confidence"), 0.7)
    time_decay = _safe_float(item.get("time_decay"), 1.0)
    reliability = source_weight * confidence * time_decay
    return float(max(BAYES_RELIABILITY_FLOOR, min(1.0, reliability)))


def bayesian_sentiment_posterior(items: list[dict]) -> dict[str, float | int | str]:
    """Normal-normal posterior for the latent sentiment mean.

    Each article contributes an observation on the legacy scaled sentiment axis
    [-2, 2]. ``source_weight``, classifier ``confidence``, and ``time_decay``
    enter as likelihood precision, not as a market-return probability.
    """
    observations: list[float] = []
    reliabilities: list[float] = []

    for item in items:
        score = _safe_float(item.get("final_score"), 0.0)
        if abs(score) < ACTIVE_SCORE_THRESHOLD:
            continue
        observations.append(score * SENTIMENT_SCORE_SCALE)
        reliabilities.append(_item_reliability(item))

    active_count = len(observations)
    if active_count == 0:
        return {
            "posterior_mean": 0.0,
            "posterior_sd": round(BAYES_PRIOR_SD, 4),
            "prob_positive": 0.5,
            "prob_negative": 0.5,
            "prob_same_direction": 0.5,
            "ci_5": round(stats.norm.ppf(0.05, loc=BAYES_PRIOR_MEAN, scale=BAYES_PRIOR_SD), 4),
            "ci_95": round(stats.norm.ppf(0.95, loc=BAYES_PRIOR_MEAN, scale=BAYES_PRIOR_SD), 4),
            "active_count": 0,
            "reliability_sum": 0.0,
            "direction": "neutral",
        }

    y = np.asarray(observations, dtype=np.float64)
    reliability = np.asarray(reliabilities, dtype=np.float64)
    base_var = BAYES_BASE_SIGMA ** 2
    prior_var = BAYES_PRIOR_SD ** 2

    obs_precision = reliability / base_var
    posterior_precision = (1.0 / prior_var) + float(obs_precision.sum())
    posterior_var = 1.0 / posterior_precision
    posterior_mean = posterior_var * (
        (BAYES_PRIOR_MEAN / prior_var) + float(np.sum(obs_precision * y))
    )
    posterior_sd = float(np.sqrt(posterior_var))
    prob_positive = float(stats.norm.sf(0.0, loc=posterior_mean, scale=posterior_sd))
    prob_negative = float(1.0 - prob_positive)
    prob_same_direction = max(prob_positive, prob_negative)

    if abs(posterior_mean) < 1e-8:
        direction = "neutral"
        prob_same_direction = 0.5
    else:
        direction = "positive" if posterior_mean > 0 else "negative"

    return {
        "posterior_mean": round(float(np.clip(posterior_mean, -2.0, 2.0)), 4),
        "posterior_sd": round(posterior_sd, 4),
        "prob_positive": round(prob_positive, 4),
        "prob_negative": round(prob_negative, 4),
        "prob_same_direction": round(float(prob_same_direction), 4),
        "ci_5": round(float(np.clip(stats.norm.ppf(0.05, loc=posterior_mean, scale=posterior_sd), -2.0, 2.0)), 4),
        "ci_95": round(float(np.clip(stats.norm.ppf(0.95, loc=posterior_mean, scale=posterior_sd), -2.0, 2.0)), 4),
        "active_count": active_count,
        "reliability_sum": round(float(reliability.sum()), 4),
        "direction": direction,
    }


def _neutral_channel_posterior() -> dict[str, float | int | str]:
    return bayesian_sentiment_posterior([])


def calculate_channel_scores_with_posteriors(
    items: list[dict],
) -> tuple[dict[str, float], dict[str, float], dict[str, dict]]:
    scores: dict[str, float] = {}
    probs: dict[str, float] = {}
    posteriors: dict[str, dict] = {}
    channel_items = {channel: [] for channel in MACRO_CHANNELS}

    for item in items:
        channel = item.get("macro_channel", "unknown")
        if channel in channel_items:
            channel_items[channel].append(item)

    for channel in MACRO_CHANNELS:
        posterior = bayesian_sentiment_posterior(channel_items[channel])
        posteriors[channel] = posterior
        scores[channel] = float(posterior["posterior_mean"])
        probs[channel] = float(posterior["prob_same_direction"])

    return scores, probs, posteriors


def calculate_channel_scores(items: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    """
    Calculate scores for each channel in MACRO_CHANNELS.
    Returns legacy score and confidence maps. New callers should use
    calculate_channel_scores_with_posteriors to access interval diagnostics.
    """
    scores, probs, _ = calculate_channel_scores_with_posteriors(items)
    return scores, probs


def build_macro_composite(channel_scores: dict[str, float]) -> float:
    """Calculate composite score based on Vietnam macro weights."""
    composite = 0.0
    for channel, weight in VN_MACRO_WEIGHTS.items():
        composite += channel_scores.get(channel, 0.0) * weight
    return round(composite, 4)


def build_macro_composite_posterior(channel_posteriors: dict[str, dict]) -> dict[str, float | int | str]:
    mean = 0.0
    variance = 0.0
    active_count = 0
    reliability_sum = 0.0

    for channel, weight in VN_MACRO_WEIGHTS.items():
        posterior = channel_posteriors.get(channel) or _neutral_channel_posterior()
        mean += float(posterior.get("posterior_mean", 0.0)) * weight
        variance += (weight ** 2) * (float(posterior.get("posterior_sd", BAYES_PRIOR_SD)) ** 2)
        active_count += int(posterior.get("active_count", 0) or 0)
        reliability_sum += float(posterior.get("reliability_sum", 0.0) or 0.0)

    sd = float(np.sqrt(max(variance, 1e-12)))
    prob_positive = float(stats.norm.sf(0.0, loc=mean, scale=sd))
    prob_negative = float(1.0 - prob_positive)
    prob_same_direction = max(prob_positive, prob_negative)
    if abs(mean) < 1e-8:
        direction = "neutral"
        prob_same_direction = 0.5
    else:
        direction = "positive" if mean > 0 else "negative"

    return {
        "posterior_mean": round(float(np.clip(mean, -2.0, 2.0)), 4),
        "posterior_sd": round(sd, 4),
        "prob_positive": round(prob_positive, 4),
        "prob_negative": round(prob_negative, 4),
        "prob_same_direction": round(float(prob_same_direction), 4),
        "ci_5": round(float(np.clip(stats.norm.ppf(0.05, loc=mean, scale=sd), -2.0, 2.0)), 4),
        "ci_95": round(float(np.clip(stats.norm.ppf(0.95, loc=mean, scale=sd), -2.0, 2.0)), 4),
        "active_count": active_count,
        "reliability_sum": round(reliability_sum, 4),
        "direction": direction,
    }


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
    channel_scores, channel_probs, channel_posteriors = calculate_channel_scores_with_posteriors(items)
    macro_posterior = build_macro_composite_posterior(channel_posteriors)
    macro_composite = float(macro_posterior["posterior_mean"])
    composite_prob = float(macro_posterior["prob_same_direction"])
        
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
        "macro_composite_posterior": macro_posterior,
        "macro_composite_prob_pos": composite_prob,
        "macro_composite_prob_positive": float(macro_posterior["prob_positive"]),
        "regime": regime,
        "channel_scores": channel_scores,
        "channel_probs": channel_probs,
        "channel_posteriors": channel_posteriors,
        "top_positive_drivers": top_pos,
        "top_negative_drivers": top_neg,
        "news_count": len(items),
        "source_counts": {
            "mozyfin": mozyfin_count,
            "widata": widata_count
        }
    }
