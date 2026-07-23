"""Snapshot hook for Data Health operational reports."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.data_manager import DataManager


def _as_of_date(df_close: pd.DataFrame | None) -> date:
    if df_close is not None and not df_close.empty:
        return pd.Timestamp(df_close.index[-1]).date()
    return date.today()


def _source_count(sources: list[dict[str, Any]], prefix: str) -> int:
    return sum(str(source.get("category", "")).startswith(prefix) for source in sources)


def _worst_source(sources: list[dict[str, Any]]) -> dict[str, Any]:
    dated = [
        source
        for source in sources
        if source.get("freshness_days") is not None
    ]
    if not dated:
        return {}
    return max(dated, key=lambda source: int(source.get("freshness_days") or 0))


def snapshot(df_close=None, load_custom=None) -> dict:
    as_of = _as_of_date(df_close)
    report = DataManager(as_of=as_of).check_data_freshness()
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    worst = _worst_source(sources)

    return {
        "snapshot_date": str(report.get("as_of", as_of.isoformat())),
        "overall_status": str(report.get("overall_status", "")),
        "source_count": int(summary.get("source_count", len(sources))),
        "healthy_count": int(summary.get("healthy", 0)),
        "warning_count": int(summary.get("warning", 0)),
        "critical_count": int(summary.get("critical", 0)),
        "raw_source_count": _source_count(sources, "raw/"),
        "processed_source_count": _source_count(sources, "processed/"),
        "tool_metric_count": _source_count(sources, "processed/tool_metrics"),
        "report_source_count": _source_count(sources, "processed/reports"),
        "missing_or_undated_count": sum(source.get("latest_data_date") is None for source in sources),
        "cache_issue_count": sum(
            str(source.get("cache_status", "")).lower() in {"warning", "critical"}
            for source in sources
        ),
        "most_stale_source": str(worst.get("name", "")),
        "most_stale_category": str(worst.get("category", "")),
        "most_stale_age_days": worst.get("freshness_days"),
        "status": "ok",
        "error": "",
    }
