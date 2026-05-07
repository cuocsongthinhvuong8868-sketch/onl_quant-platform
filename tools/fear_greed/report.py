from config import DEFAULT_WINDOW, RANK_WINDOW
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import calculate_risk_score


def snapshot(df_close, _load_custom):
    metrics = calculate_quant_metrics(df_close, window_size=DEFAULT_WINDOW)
    scored = calculate_risk_score(metrics, rank_window=RANK_WINDOW)
    latest = scored.iloc[-1]
    return {
        "snapshot_date": scored.index[-1].strftime("%Y-%m-%d"),
        "risk_score": round(float(latest["Risk_Score"]), 3),
        "vol_norm": round(float(latest["Vol_Norm"]), 4),
        "skewness": round(float(latest["Skewness"]), 4),
        "down_corr_norm": round(float(latest["Down_Corr_Norm"]), 4),
        "up_corr_norm": round(float(latest["Up_Corr_Norm"]), 4),
    }
