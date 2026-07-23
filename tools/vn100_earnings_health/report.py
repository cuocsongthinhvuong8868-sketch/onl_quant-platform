"""Snapshot hook for VN100 Corporate Health reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tools.vn100_earnings_health.quant.config import OUTPUT_DIR


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing VN100 Corporate Health output: {path}")
    return pd.read_csv(path)


def _read_summary(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "run_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _int_or_zero(value: Any) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def _stringify_diagnosis(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    text = str(value)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return "; ".join(str(item) for item in parsed)
    except Exception:
        pass
    return text


def _sector_extreme(sector_scores: pd.DataFrame, ascending: bool) -> pd.Series:
    if sector_scores.empty or "sector_health_score" not in sector_scores.columns:
        return pd.Series(dtype=object)
    ordered = sector_scores.dropna(subset=["sector_health_score"]).sort_values(
        "sector_health_score",
        ascending=ascending,
    )
    if ordered.empty:
        return pd.Series(dtype=object)
    return ordered.iloc[0]


def snapshot(df_close=None, load_custom=None) -> dict:
    output_dir = Path(OUTPUT_DIR)
    summary = _read_summary(output_dir)
    vn100 = _read_csv(output_dir / "vn100_scores_latest_yoy.csv")
    sector = _read_csv(output_dir / "sector_scores_latest_yoy.csv")
    alerts = _read_csv(output_dir / "alerts.csv")

    if vn100.empty:
        raise ValueError("VN100 latest YoY score output is empty")

    latest = vn100.iloc[-1]
    top_sector = _sector_extreme(sector, ascending=False)
    weak_sector = _sector_extreme(sector, ascending=True)
    critical_alerts = alerts.loc[alerts.get("alert_level", pd.Series(dtype=object)).eq("Critical")]

    return {
        "snapshot_date": str(latest.get("period", summary.get("latest_yoy_period", ""))),
        "mode": "YoY",
        "latest_qoq_period": summary.get("latest_qoq_period", ""),
        "latest_yoy_period": summary.get("latest_yoy_period", ""),
        "ticker_count": _int_or_zero(summary.get("tickers", latest.get("valid_company_count"))),
        "period_count": _int_or_zero(summary.get("periods")),
        "vn100_health_score": _float_or_none(latest.get("vn100_health_score")),
        "vn100_health_score_market_cap_weighted": _float_or_none(
            latest.get("vn100_health_score_market_cap_weighted")
        ),
        "valid_company_count": _int_or_zero(latest.get("valid_company_count")),
        "positive_sector_count": _int_or_zero(latest.get("positive_sector_count")),
        "valid_sector_count": _int_or_zero(latest.get("valid_sector_count")),
        "regime": str(latest.get("regime", "N/A")),
        "revenue_breadth": _float_or_none(latest.get("revenue_breadth")),
        "profit_breadth": _float_or_none(latest.get("profit_breadth")),
        "cfo_breadth": _float_or_none(latest.get("cfo_breadth")),
        "healthy_growth_breadth": _float_or_none(latest.get("healthy_growth_breadth")),
        "working_capital_stress_index": _float_or_none(
            latest.get("working_capital_stress_index")
        ),
        "leverage_stress_index": _float_or_none(latest.get("leverage_stress_index")),
        "sector_diffusion_score": _float_or_none(latest.get("sector_diffusion_score")),
        "main_diagnosis": _stringify_diagnosis(latest.get("main_diagnosis")),
        "top_sector": str(top_sector.get("sector", "")),
        "top_sector_health_score": _float_or_none(top_sector.get("sector_health_score")),
        "weakest_sector": str(weak_sector.get("sector", "")),
        "weakest_sector_health_score": _float_or_none(weak_sector.get("sector_health_score")),
        "alert_count": int(len(alerts)),
        "critical_alert_count": int(len(critical_alerts)),
        "top_critical_alert_ticker": (
            str(critical_alerts.iloc[0].get("ticker", "")) if not critical_alerts.empty else ""
        ),
        "status": "ok",
        "error": "",
    }
