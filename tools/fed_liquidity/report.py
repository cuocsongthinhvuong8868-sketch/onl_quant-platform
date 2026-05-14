"""
tools/fed_liquidity/report.py
Snapshot hook cho AI CIO / report engine.
"""
import pandas as pd
from config import DATA_LAKE
from tools.fed_liquidity.quant.metrics import OUTPUT_COLUMNS, summarize_latest

FED_LIQUIDITY_FILE = "fed_liquidity_cache.csv"


def snapshot(df_close=None, load_custom=None) -> dict:
    """
    Snapshot hook chuẩn cho discovery engine.

    Đọc cache CSV (đã được updater fill sẵn) và trả về dict latest metrics.
    Giữ chữ ký giống các snapshot khác để tương thích `generate_report.py`.
    """
    path = DATA_LAKE / FED_LIQUIDITY_FILE
    if not path.exists():
        return {
            "date": "",
            "net_liquidity": 0.0,
            "impulse": 0.0,
            "impulse_ema": 0.0,
            "z_score": 0.0,
            "signal": "N/A",
            "walcl": 0.0,
            "wtregen": 0.0,
            "rrpontsyd": 0.0,
            "status": "error",
            "error": "fed_liquidity_cache.csv not found — run command/update_fed_liquidity.py",
        }

    df = pd.read_csv(path, parse_dates=["DATE"]).set_index("DATE").sort_index()
    numeric_cols = [c for c in OUTPUT_COLUMNS if c != "Signal"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    summary = summarize_latest(df)
    summary["status"] = "ok"
    summary["error"] = ""
    return summary
