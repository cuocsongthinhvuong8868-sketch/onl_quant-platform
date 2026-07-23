from shared.data_loader import load_custom
from tools.dispersion.quant.metrics import (
    calculate_dispersion_metrics,
    determine_macro_regime,
    fit_rolling_correlation,
    summarize_dispersion_state,
)


def snapshot(df_close, _load_custom):
    df_idx = load_custom("vnindex_cache.csv")
    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    s = df_idx[idx_col]

    stock_returns, metrics = calculate_dispersion_metrics(df_close, s, zscore_window=60, dpi_window=60)
    metrics["Ledoit_Correlation"] = fit_rolling_correlation(stock_returns, window=30, refit_every=5)
    metrics["Macro_Regime"] = determine_macro_regime(metrics, dpi_thresh=50, corr_dist=0.20, corr_cap=0.35)
    metrics = metrics.dropna(subset=["DPI", "Ledoit_Correlation"])
    if metrics.empty:
        raise ValueError("Dispersion metrics rỗng sau khi xử lý")

    last = metrics.iloc[-1]
    summary = summarize_dispersion_state(metrics)
    return {
        "snapshot_date": metrics.index[-1].strftime("%Y-%m-%d"),
        "methodology_version": summary["methodology_version"],
        "dpi": round(float(last["DPI"]), 3),
        "ledoit_corr": round(float(last["Ledoit_Correlation"]), 6),
        "macro_regime": str(last["Macro_Regime"]),
        "spread_z": round(float(last["Spread_Z"]), 4),
        "csad_z": round(float(last["CSAD_Z"]), 4),
        "cssd_z": round(float(last["CSSD_Z"]), 4),
        "cs_skewness": round(float(last["CS_Skewness"]), 4),
        "cs_kurtosis": round(float(last["CS_Kurtosis"]), 4),
        "downside_participation_pct": round(float(last["Downside_Participation"]), 3),
        "upside_participation_pct": round(float(last["Upside_Participation"]), 3),
        "broad_stress_score": round(float(summary["broad_stress_score"]), 2),
        "broad_stress_level": summary["broad_stress_level"],
        "effective_names": int(last["Effective_Names"]),
    }
