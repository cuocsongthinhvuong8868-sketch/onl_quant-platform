from shared.data_loader import load_custom
from tools.dispersion.quant.metrics import calculate_dispersion_metrics, fit_rolling_correlation, determine_macro_regime


def snapshot(df_close, _load_custom):
    df_idx = load_custom("vnindex_cache.csv")
    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    s = df_idx[idx_col]

    stock_returns, metrics = calculate_dispersion_metrics(df_close, s, zscore_window=60, dpi_window=60)
    metrics["Ledoit_Correlation"] = fit_rolling_correlation(stock_returns, window=30, refit_every=1)
    metrics["Macro_Regime"] = determine_macro_regime(metrics, dpi_thresh=50, corr_dist=0.20, corr_cap=0.35)
    metrics = metrics.dropna(subset=["DPI", "Ledoit_Correlation"])
    if metrics.empty:
        raise ValueError("Dispersion metrics rỗng sau khi xử lý")

    last = metrics.iloc[-1]
    return {
        "snapshot_date": metrics.index[-1].strftime("%Y-%m-%d"),
        "dpi": round(float(last["DPI"]), 3),
        "ledoit_corr": round(float(last["Ledoit_Correlation"]), 6),
        "macro_regime": str(last["Macro_Regime"]),
    }
