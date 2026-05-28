"""
tools/vnibor/report.py
Snapshot hook for AI CIO / report engine.
"""
import pandas as pd
from config import DATA_LAKE
from tools.vnibor.quant.metrics import load_vnibor_data, process_vnibor_logic, summarize_latest

def snapshot(df_close=None, load_custom=None) -> dict:
    """
    Snapshot hook chuẩn cho discovery engine.
    """
    try:
        df_raw = load_vnibor_data()
        df_processed = process_vnibor_logic(df_raw)
        summary = summarize_latest(df_processed)
        summary["status"] = "ok"
        summary["error"] = ""
        return summary
    except Exception as e:
        return {
            "date": "N/A", "overnight": 0.0, "w1": 0.0, "w2": 0.0,
            "impulse": 0.0, "z_score": 0.0, "percentile": 0.0,
            "spread_1w": 0.0, "spread_2w": 0.0, "regime": "N/A", "signal": "N/A",
            "status": "error",
            "error": str(e)
        }
