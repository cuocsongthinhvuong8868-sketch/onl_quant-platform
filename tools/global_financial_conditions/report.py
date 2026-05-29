"""
tools/global_financial_conditions/report.py
Snapshot hook cho AI / report engine.
"""

from config import DATA_LAKE
from tools.global_financial_conditions.quant.metrics import (
    load_cached_gfcm,
    summarize_latest,
)

GFCM_FILE = "global_financial_conditions_cache.csv"


def snapshot(df_close=None, load_custom=None) -> dict:
    """
    Snapshot chuẩn cho discovery engine.
    Đọc cache CSV (đã được updater fill sẵn) và trả về dict latest metrics.
    """
    path = DATA_LAKE / GFCM_FILE
    if not path.exists():
        out = {
            "date": "", "vix": 0.0, "move": 0.0, "hy_oas": 0.0, "ccc_oas": 0.0,
            "credit_quality_spread": 0.0,
            "vix_pct": 0.0, "move_pct": 0.0, "hy_pct": 0.0, "ccc_pct": 0.0,
            "cqs_pct": 0.0,
            "vix_z": 0.0, "move_z": 0.0, "hy_z": 0.0, "ccc_z": 0.0,
            "pc1": 0.0, "pc2": 0.0, "pc1_pct": 0.0,
            "regime": "N/A", "driver": "N/A", "pc1_5d_change": 0.0,
            "status": "error",
            "error": f"{GFCM_FILE} not found — run command/update_global_financial_conditions.py",
        }
        return out

    df = load_cached_gfcm(path)

    summary = summarize_latest(df)
    summary["status"] = "ok"
    summary["error"] = ""
    return summary
