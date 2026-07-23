from config import DEFAULT_WINDOW, RANK_WINDOW
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import METHOD_VERSION, calculate_risk_score


def _rounded(latest, key: str, digits: int):
    value = latest.get(key)
    if value is None or value != value:
        return None
    return round(float(value), digits)


def snapshot(df_close, _load_custom):
    metrics = calculate_quant_metrics(df_close, window_size=DEFAULT_WINDOW)
    scored = calculate_risk_score(metrics, rank_window=RANK_WINDOW)
    latest = scored.iloc[-1]
    return {
        "snapshot_date": scored.index[-1].strftime("%Y-%m-%d"),
        "methodology_version": latest.get("Methodology_Version", METHOD_VERSION),
        "risk_score": _rounded(latest, "Risk_Score", 3),
        "risk_score_raw": _rounded(latest, "Risk_Score_Raw", 3),
        "sentiment_regime": latest.get("Sentiment_Regime"),
        "signal_confidence": _rounded(latest, "Signal_Confidence", 4),
        "panic_pull": _rounded(latest, "Panic_Pull", 4),
        "fomo_push": _rounded(latest, "Fomo_Push", 4),
        "net_sentiment_pressure": _rounded(latest, "Net_Sentiment_Pressure", 4),
        "market_impulse_3d": _rounded(latest, "Market_Impulse_3D", 6),
        "market_impulse_5d": _rounded(latest, "Market_Impulse_5D", 6),
        "acute_shock": _rounded(latest, "Acute_Shock", 4),
        "positive_impulse": _rounded(latest, "Positive_Impulse", 4),
        "shock_score_cap": _rounded(latest, "Shock_Score_Cap", 2),
        "shock_regime_flag": latest.get("Shock_Regime_Flag"),
        "vol_norm": _rounded(latest, "Vol_Norm", 4),
        "skewness": _rounded(latest, "Skewness", 4),
        "down_corr_norm": _rounded(latest, "Down_Corr_Norm", 4),
        "up_corr_norm": _rounded(latest, "Up_Corr_Norm", 4),
        "csv_norm": _rounded(latest, "CSV_Norm", 4),
        "csv_index": _rounded(latest, "CSV_Index", 8),
        "dispersion_stress": _rounded(latest, "Dispersion_Stress", 4),
    }
