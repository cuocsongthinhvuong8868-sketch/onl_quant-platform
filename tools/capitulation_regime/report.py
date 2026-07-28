"""Snapshot hook for Capitulation Regime diagnostics."""
from __future__ import annotations

from typing import Any

import pandas as pd

from shared.data_loader import load_close_prices, load_custom, load_volumes
from tools.capitulation_regime import analyze_capitulation


PCT_FEATURES = {
    "return_1d",
    "return_5d",
    "drawdown",
    "ma200_gap",
    "breadth_ma20",
    "downside_participation",
    "new_low_252",
    "turnover_coverage",
}


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


def _pct_or_none(value: Any, digits: int = 2) -> float | None:
    number = _float_or_none(value, digits + 2)
    if number is None:
        return None
    return round(number * 100.0, digits)


def _feature(features: dict[str, Any], key: str) -> float | None:
    value = features.get(key)
    if key in PCT_FEATURES:
        return _pct_or_none(value)
    return _float_or_none(value, 4)


def _gate(gates: dict[str, Any], key: str) -> bool:
    return gates.get(key) is True


def _first(items: Any) -> str:
    if isinstance(items, (list, tuple)) and items:
        return str(items[0])
    return ""


def _load_abm_metrics() -> dict[str, Any] | None:
    try:
        from tools.abm_simulator import report as abm_report

        return abm_report.snapshot()
    except Exception:
        return None


def snapshot(df_close=None, load_custom=None) -> dict:
    constituent_close = (df_close if df_close is not None else load_close_prices()).sort_index()
    if constituent_close.empty:
        raise ValueError("constituent close data is empty")

    custom_loader = load_custom or globals()["load_custom"]
    index_frame = custom_loader("vnindex_cache.csv")
    normalized_columns = {str(column).strip().lower(): column for column in index_frame.columns}
    close_column = normalized_columns.get("vnindex")
    if close_column is None:
        raise ValueError("vnindex_cache.csv has no VNINDEX close column")
    volume_column = normalized_columns.get("vnindex_volume")
    constituent_volume = load_volumes()
    abm_metrics = _load_abm_metrics()

    snapshot_obj = analyze_capitulation(
        index_close=index_frame[close_column],
        constituent_close=constituent_close,
        index_volume=index_frame[volume_column] if volume_column is not None else None,
        constituent_volume=constituent_volume,
        abm_metrics=abm_metrics,
        as_of=constituent_close.index[-1],
    )
    state = snapshot_obj.to_dict()
    features = state.get("features") if isinstance(state.get("features"), dict) else {}
    percentiles = state.get("percentiles") if isinstance(state.get("percentiles"), dict) else {}
    gates = state.get("required_gates_met") if isinstance(state.get("required_gates_met"), dict) else {}
    quality = state.get("data_quality") if isinstance(state.get("data_quality"), dict) else {}
    trigger_reasons = state.get("trigger_reasons") or []
    confirmation_reasons = state.get("confirmation_reasons") or []

    return {
        "snapshot_date": str(state.get("as_of", ""))[:10],
        "phase": str(state.get("phase", "")),
        "sessions_after_three_gate_climax": state.get(
            "sessions_after_three_gate_climax"
        ),
        "action_eligible": state.get("action_eligible") is True,
        "stress_risk_score_uncalibrated": _float_or_none(
            state.get("stress_risk_score_uncalibrated"),
            1,
        ),
        "liquidation_risk_score_uncalibrated": _float_or_none(
            state.get("liquidation_risk_score_uncalibrated"),
            1,
        ),
        "exhaustion_evidence_score_uncalibrated": _float_or_none(
            state.get("exhaustion_evidence_score_uncalibrated"),
            1,
        ),
        "return_1d_pct": _feature(features, "return_1d"),
        "return_5d_pct": _feature(features, "return_5d"),
        "drawdown_pct": _feature(features, "drawdown"),
        "ma200_gap_pct": _feature(features, "ma200_gap"),
        "breadth_ma20_pct": _feature(features, "breadth_ma20"),
        "downside_participation_pct": _feature(features, "downside_participation"),
        "new_low_252_pct": _feature(features, "new_low_252"),
        "turnover_ratio_20": _feature(features, "turnover_ratio_20"),
        "daily_loss_percentile": _float_or_none(percentiles.get("daily_loss"), 4),
        "price_shock_gate": _gate(gates, "price_shock"),
        "breadth_shock_gate": _gate(gates, "breadth_shock"),
        "forced_selling_gate": _gate(gates, "forced_selling"),
        "three_gate_climax_gate": _gate(gates, "three_gate_climax"),
        "climax_continuation_gate": _gate(gates, "climax_continuation"),
        "post_climax_exhaustion_gate": _gate(gates, "post_climax_exhaustion"),
        "data_quality_status": str(quality.get("status", "")),
        "constituent_count": int(quality.get("constituent_count", 0) or 0),
        "breadth_coverage_pct": _pct_or_none(quality.get("current_breadth_coverage")),
        "volume_coverage_pct": _pct_or_none(quality.get("current_volume_coverage")),
        "data_quality_warning_count": len(quality.get("warnings") or []),
        "trigger_reason_count": len(trigger_reasons),
        "first_trigger_reason": _first(trigger_reasons),
        "confirmation_reason_count": len(confirmation_reasons),
        "first_confirmation_reason": _first(confirmation_reasons),
        "abm_metrics_used": abm_metrics is not None,
        "methodology_version": str(state.get("methodology_version", "")),
        "status": "ok",
        "error": "",
    }
