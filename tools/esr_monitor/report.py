from shared.data_loader import load_custom
from tools.esr_monitor.quant.metrics import calculate_esr


def snapshot(df_close, _load_custom):
    df_index = load_custom("vnindex_cache.csv")
    df, _ = calculate_esr(df_close, df_index, ma_period=125, pca_window=60)
    last = df.iloc[-1]
    return {
        "snapshot_date": df.index[-1].strftime("%Y-%m-%d"),
        "ssi": round(float(last["SSI_Index"]), 6),
        "index_close": round(float(last["INDEX_Close"]), 2),
        "status": "SAFE" if last["SSI_Index"] < 0.5 else "WARNING" if last["SSI_Index"] < 0.8 else "CRITICAL",
    }
