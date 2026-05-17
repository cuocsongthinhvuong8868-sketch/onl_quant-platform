import pandas as pd
from tools.var_cvar_vnindex.quant.metrics import calculate_var_cvar_metrics


def _empty_snapshot(err: str = "") -> dict:
    """Khung dữ liệu fallback — đảm bảo prompt template không vỡ vì key thiếu."""
    return {
        "date": "",
        "vnindex_price": 0.0,
        "stdev_30": 0.0,
        "parametric_var": 0.0,
        "historical_var": 0.0,
        "expected_shortfall": 0.0,
        "es_var_spread": 0.0,
        # EVT fields
        "evt_var_95": 0.0, "evt_var_99": 0.0, "evt_var_995": 0.0,
        "evt_es_95": 0.0, "evt_es_99": 0.0, "evt_es_995": 0.0,
        "evt_xi": 0.0, "evt_beta": 0.0, "evt_threshold": 0.0,
        "evt_n_exceed": 0, "hill_index": 0.0,
        "evt_available": False,
        "status": "error" if err else "ok",
        "error": err,
    }


def snapshot(df_close: pd.DataFrame, load_custom=None) -> dict:
    """
    Snapshot hook cho AI CIO.
    Tính VaR-CVaR + EVT cho VNINDEX và trả về dict với giá trị mới nhất.
    """
    try:
        if load_custom is None:
            from shared.data_loader import load_custom as _lc
            load_custom = _lc
        df_vni = load_custom("vnindex_cache.csv")
        idx_col = "VNINDEX" if "VNINDEX" in df_vni.columns else df_vni.columns[0]
        vni_series = df_vni[idx_col]
    except FileNotFoundError:
        return _empty_snapshot(err="VNINDEX cache not found")

    df_metrics = calculate_var_cvar_metrics(vni_series, include_evt=True)
    # Lấy ngày cuối có đủ data classic (EVT có thể NaN nếu < 756d)
    df_classic = df_metrics.dropna(subset=["historical_var", "expected_shortfall"])
    if df_classic.empty:
        return _empty_snapshot(err="Insufficient data for VaR-CVaR")
    latest = df_classic.iloc[-1]
    latest_date = df_classic.index[-1]

    snap = _empty_snapshot()
    snap.update({
        "date": latest_date.strftime('%d/%m/%Y'),
        "vnindex_price": float(latest['price']),
        "stdev_30": float(latest['stdev_30']),
        "parametric_var": float(latest['parametric_var']),
        "historical_var": float(latest['historical_var']),
        "expected_shortfall": float(latest['expected_shortfall']),
        "es_var_spread": float(latest['expected_shortfall'] - latest['historical_var']),
        "status": "ok",
        "error": "",
    })

    # EVT fields — chỉ populate nếu data đủ
    if 'evt_var_99' in df_metrics.columns and pd.notna(latest.get('evt_var_99')):
        snap.update({
            "evt_var_95": float(latest['evt_var_95']),
            "evt_var_99": float(latest['evt_var_99']),
            "evt_var_995": float(latest['evt_var_995']),
            "evt_es_95": float(latest['evt_es_95']),
            "evt_es_99": float(latest['evt_es_99']),
            "evt_es_995": float(latest['evt_es_995']),
            "evt_xi": float(latest['evt_xi']),
            "evt_beta": float(latest['evt_beta']),
            "evt_threshold": float(latest['evt_threshold']),
            "evt_n_exceed": int(latest['evt_n_exceed']),
            "hill_index": float(latest['hill_index']),
            "evt_available": True,
        })

    return snap
