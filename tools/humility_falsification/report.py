"""Snapshot hook for Humility & Falsification Monitor reports."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_LAKE


RESULT_CACHE_PREFIX = "humility_falsification"
FALSIFICATION_CUTOFF = 3


def _cache_dir() -> Path:
    return Path(DATA_LAKE) / "daily_cache"


def _cache_date(path: Path) -> date | None:
    match = re.match(rf"{re.escape(RESULT_CACHE_PREFIX)}_.+_(\d{{6}})\.json$", path.name)
    if not match:
        return None
    raw = match.group(1)
    try:
        return date(2000 + int(raw[4:6]), int(raw[2:4]), int(raw[:2]))
    except ValueError:
        return None


def _latest_cache() -> Path:
    files = list(_cache_dir().glob(f"{RESULT_CACHE_PREFIX}_*.json"))
    if not files:
        raise FileNotFoundError(f"Missing Humility/Falsification cache in {_cache_dir()}")
    return max(files, key=lambda path: (_cache_date(path) or date.min, path.stat().st_mtime))


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except Exception:
        return True


def _float_or_none(value: Any, digits: int = 4) -> float | None:
    if not _is_present(value):
        return None
    return round(float(value), digits)


def _int_or_zero(value: Any) -> int:
    if not _is_present(value):
        return 0
    return int(float(value))


def _boolish(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "falsified"}
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


def _row_is_falsified(row: dict[str, Any]) -> bool:
    if "Falsified" in row:
        return _boolish(row.get("Falsified"))
    return str(row.get("Status", "")).strip().upper() == "FALSIFIED"


def _first_falsified(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if _row_is_falsified(row):
            return row
    return {}


def _metric_date_bounds(rows: list[dict[str, Any]]) -> tuple[str, str]:
    dates = pd.to_datetime(
        [row.get("Data date") for row in rows if _is_present(row.get("Data date"))],
        errors="coerce",
    ).dropna()
    if dates.empty:
        return "", ""
    return dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")


def _error_count(current_metrics: dict[str, Any]) -> int:
    return sum(
        1
        for metric in current_metrics.values()
        if isinstance(metric, dict) and str(metric.get("error") or "").strip()
    )


def snapshot(df_close=None, load_custom=None) -> dict:
    cache_path = _latest_cache()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    parsed = payload.get("parsed") if isinstance(payload.get("parsed"), dict) else {}
    current_metrics = (
        payload.get("current_metrics") if isinstance(payload.get("current_metrics"), dict) else {}
    )
    falsified = _int_or_zero(payload.get("falsified", sum(_row_is_falsified(row) for row in rows)))
    total = _int_or_zero(payload.get("total", len(rows)))
    available = _int_or_zero(payload.get("available", total))
    first_falsified = _first_falsified(rows)
    metric_min_date, metric_max_date = _metric_date_bounds(rows)

    return {
        "snapshot_date": str(payload.get("t_data_date", _cache_date(cache_path) or "")),
        "target_report_date": str(payload.get("target_report_date", "")),
        "provider_key": str(payload.get("provider_key", "")),
        "cache_file": cache_path.name,
        "report_name": str(payload.get("report_name") or Path(str(payload.get("report_path", ""))).name),
        "report_match": str(payload.get("report_match", "")),
        "parse_mode": str(parsed.get("parse_mode", "")),
        "source_report_date": str(parsed.get("report_date", "")),
        "source_composite_score": _float_or_none(parsed.get("composite_score"), 2),
        "source_regime": str(parsed.get("regime", "")),
        "thesis_status": str(payload.get("status_label", "")),
        "status_help": str(payload.get("status_help", "")),
        "falsified_rule_count": falsified,
        "available_metric_count": available,
        "total_rule_count": total,
        "falsification_cutoff": FALSIFICATION_CUTOFF,
        "falsification_ratio_pct": (
            round(falsified / total * 100.0, 2) if total else None
        ),
        "thesis_falsified": falsified >= FALSIFICATION_CUTOFF,
        "first_falsified_model": str(first_falsified.get("Model", "")),
        "first_falsified_metric": str(first_falsified.get("Metric", "")),
        "first_falsified_actual": _float_or_none(first_falsified.get("T actual"), 4),
        "first_falsified_threshold": str(first_falsified.get("T-1 threshold", "")),
        "metric_error_count": _error_count(current_metrics),
        "metric_min_date": metric_min_date,
        "metric_max_date": metric_max_date,
        "status": "ok",
        "error": "",
    }
