from shared.data_loader import load_close_prices
from tools.manipulation.quant.engine import prepare_data, compute_metrics


def snapshot(_df_close, _load_custom):
    df = prepare_data(load_close_prices())
    _, result = compute_metrics(df, window=60)
    if result.empty:
        raise ValueError("Manipulation result rỗng")
    last = result.iloc[-1]
    return {
        "snapshot_date": result.index[-1].strftime("%Y-%m-%d"),
        "manip_corr": round(float(last["Correlation"]), 6),
        "manip_slope": round(float(last["OLS_Slope"]), 6),
        "manip_pr_corr": round(float(last["PR_Corr"]), 6),
        "manip_pr_slope": round(float(last["PR_Slope"]), 6),
    }
