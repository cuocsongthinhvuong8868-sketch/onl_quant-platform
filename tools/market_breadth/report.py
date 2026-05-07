from tools.market_breadth.quant.metrics import compute_breadth


def snapshot(df_close, _load_custom):
    breadth, _ = compute_breadth(df_close)
    latest = breadth.iloc[-1]
    return {
        "snapshot_date": breadth.index[-1].strftime("%Y-%m-%d"),
        "above_ma20": int(latest["> MA20"]),
        "above_ma60": int(latest["> MA60"]),
        "above_ma125": int(latest["> MA125"]),
        "above_ma252": int(latest["> MA252"]),
        "universe_size": int(df_close.shape[1]),
    }
