import pandas as pd
from tools.var_cvar_vnindex.quant.metrics import calculate_var_cvar_metrics


def snapshot(df_close: pd.DataFrame, load_custom=None) -> dict:
    """
    Snapshot hook cho AI CIO.
    Tính VaR-CVaR cho VNINDEX và trả về dict với giá trị mới nhất.
    """
    try:
        if load_custom is None:
            from shared.data_loader import load_custom as _lc
            load_custom = _lc
        
        df_vni = load_custom("vnindex_cache.csv")
        idx_col = "VNINDEX" if "VNINDEX" in df_vni.columns else df_vni.columns[0]
        vni_series = df_vni[idx_col]
    except FileNotFoundError:
        return {
            "date": "",
            "vnindex_price": 0.0,
            "stdev_30": 0.0,
            "parametric_var": 0.0,
            "historical_var": 0.0,
            "expected_shortfall": 0.0,
            "es_var_spread": 0.0,
            "status": "error",
            "error": "VNINDEX cache not found"
        }

    df_metrics = calculate_var_cvar_metrics(vni_series)
    latest = df_metrics.dropna().iloc[-1]
    latest_date = df_metrics.dropna().index[-1]

    return {
        "date": latest_date.strftime('%d/%m/%Y'),
        "vnindex_price": float(latest['price']),
        "stdev_30": float(latest['stdev_30']),
        "parametric_var": float(latest['parametric_var']),
        "historical_var": float(latest['historical_var']),
        "expected_shortfall": float(latest['expected_shortfall']),
        "es_var_spread": float(latest['expected_shortfall'] - latest['historical_var']),
        "status": "ok",
        "error": ""
    }
