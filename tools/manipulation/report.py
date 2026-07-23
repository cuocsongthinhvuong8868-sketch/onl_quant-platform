from shared.data_loader import load_close_prices
from tools.manipulation.quant.engine import METHOD_VERSION, TARGET, prepare_data, compute_metrics


def snapshot(_df_close, _load_custom):
    load_custom = _load_custom
    if load_custom is None:
        from shared.data_loader import load_custom as _lc
        load_custom = _lc
    df_idx = load_custom("vnindex_cache.csv")
    idx_col = TARGET if TARGET in df_idx.columns else df_idx.columns[0]
    df = prepare_data(load_close_prices(), target_series=df_idx[idx_col])
    _, result = compute_metrics(df, window=60)
    if result.empty:
        raise ValueError("Manipulation result rỗng")
    last = result.iloc[-1]
    return {
        "snapshot_date": result.index[-1].strftime("%Y-%m-%d"),
        "methodology_version": METHOD_VERSION,
        "target": TARGET,
        "manip_corr": round(float(last["Correlation"]), 6),
        "manip_slope": round(float(last["OLS_Slope"]), 6),
        "manip_pr_corr": round(float(last["PR_Corr"]), 6),
        "manip_pr_slope": round(float(last["PR_Slope"]), 6),
    }
