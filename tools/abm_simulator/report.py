"""Snapshot hook for ABM Market Simulator reports."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    from config import DATA_LAKE
except Exception:
    DATA_LAKE = Path(__file__).resolve().parents[2] / "data_lake"


REQUIRED_TABLES = {
    "state": "abm_behavioral_state",
    "stress": "abm_stress_test",
    "alert": "abm_alert",
}
OPTIONAL_TABLES = {
    "latent": "abm_latent_state",
    "validation": "abm_validation",
}


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except Exception:
        return True


def _load_latest(table: str, *, required: bool = False) -> dict[str, Any]:
    path = Path(DATA_LAKE) / f"{table}.csv"
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing ABM output: {path}")
        return {}

    data = pd.read_csv(path)
    if data.empty:
        if required:
            raise ValueError(f"ABM output is empty: {path}")
        return {}

    if "as_of_date" in data.columns:
        data["as_of_date"] = pd.to_datetime(data["as_of_date"], errors="coerce")
        data = data.dropna(subset=["as_of_date"]).sort_values("as_of_date")
        if data.empty:
            if required:
                raise ValueError(f"ABM output has no valid as_of_date: {path}")
            return {}

    return data.iloc[-1].to_dict()


def _get(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = row.get(name)
        if _is_present(value):
            return value
    return default


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return default


def _float_or_none(value: Any, digits: int = 4) -> float | None:
    if not _is_present(value):
        return None
    return round(float(value), digits)


def _ratio_to_pct(value: Any, digits: int = 2) -> float | None:
    number = _float_or_none(value, digits + 2)
    if number is None:
        return None
    return round(number * 100.0, digits)


def _int_or_none(value: Any) -> int | None:
    if not _is_present(value):
        return None
    return int(float(value))


def _bool_or_none(value: Any) -> bool | None:
    if not _is_present(value):
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _date_label(value: Any) -> str:
    if not _is_present(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    parsed = pd.to_datetime(value, errors="coerce")
    if _is_present(parsed):
        return parsed.strftime("%Y-%m-%d")
    return str(value)


def _format_warning_basis(value: Any) -> str:
    if not _is_present(value):
        return ""
    parts = [
        part.strip().replace("_", " ").capitalize()
        for part in str(value).split(",")
        if part.strip()
    ]
    return "; ".join(parts)


def snapshot(df_close=None, load_custom=None) -> dict:
    state = _load_latest(REQUIRED_TABLES["state"], required=True)
    stress = _load_latest(REQUIRED_TABLES["stress"], required=True)
    alert = _load_latest(REQUIRED_TABLES["alert"], required=True)
    latent = _load_latest(OPTIONAL_TABLES["latent"])
    validation = _load_latest(OPTIONAL_TABLES["validation"])

    snapshot_date = _date_label(_first(alert.get("as_of_date"), state.get("as_of_date")))
    warning_basis = _get(alert, "warning_basis", default="")
    panel_used = _first(
        alert.get("alert_uses_quant_platform_panel"),
        state.get("qp_panel_available"),
    )

    return {
        "snapshot_date": snapshot_date,
        "regime_flag": str(_first(alert.get("regime_flag"), state.get("regime_flag"), default="")),
        "early_warning_score": _float_or_none(_get(alert, "early_warning_score"), 2),
        "early_warning_level": str(_get(alert, "early_warning_level", default="")),
        "warning_basis": str(warning_basis),
        "warning_basis_display": _format_warning_basis(warning_basis),
        "uses_quant_platform_panel": _bool_or_none(panel_used),
        "distance_to_cascade_pct": _ratio_to_pct(_get(alert, "distance_to_cascade")),
        "panic_ratio_pct": _ratio_to_pct(_get(stress, "panic_ratio")),
        "dd_exogenous_pct": _ratio_to_pct(_get(stress, "dd_exogenous")),
        "dd_endogenous_pct": _ratio_to_pct(_get(stress, "dd_endogenous")),
        "dd_total_pct": _ratio_to_pct(_get(stress, "dd_total")),
        "margin_call_events": _int_or_none(_get(stress, "margin_call_events", "margin_calls")),
        "simulation_runs": _int_or_none(_get(stress, "simulation_runs")),
        "stress_confidence_pct": _ratio_to_pct(
            _first(alert.get("stress_confidence"), stress.get("stress_confidence"))
        ),
        "input_quality_score_pct": _ratio_to_pct(
            _first(alert.get("input_quality_score"), state.get("input_quality_score"))
        ),
        "qp_panel_quality_pct": _ratio_to_pct(_get(state, "qp_panel_quality")),
        "avg_leverage_ratio": _float_or_none(_get(state, "avg_leverage_ratio"), 4),
        "pct_fundamental": _ratio_to_pct(_get(state, "pct_fundamental")),
        "pct_momentum": _ratio_to_pct(_get(state, "pct_momentum")),
        "pct_foreign": _ratio_to_pct(_get(state, "pct_foreign")),
        "pct_leveraged": _ratio_to_pct(_get(state, "pct_leveraged")),
        "pct_noise": _ratio_to_pct(_get(state, "pct_noise")),
        "mli": _float_or_none(_first(state.get("mli"), latent.get("mli")), 4),
        "liquidity_stress": _float_or_none(
            _first(state.get("liquidity_stress"), latent.get("liquidity_stress")),
            4,
        ),
        "valuation_gap_pct": _ratio_to_pct(_get(state, "valuation_gap")),
        "trend_z": _float_or_none(_get(state, "trend_z"), 4),
        "breadth_z": _float_or_none(_get(state, "breadth_z"), 4),
        "foreign_flow_z": _float_or_none(_get(state, "foreign_flow_z"), 4),
        "margin_pressure_z": _float_or_none(_get(state, "margin_pressure_z"), 4),
        "margin_leverage_level": _float_or_none(
            _first(state.get("margin_leverage_level"), latent.get("margin_leverage_level")),
            4,
        ),
        "margin_call_trigger_pressure": _float_or_none(
            _first(
                state.get("margin_call_trigger_pressure"),
                latent.get("margin_call_trigger_pressure"),
            ),
            4,
        ),
        "cascade_vulnerability": _float_or_none(
            _first(state.get("cascade_vulnerability"), latent.get("cascade_vulnerability")),
            4,
        ),
        "latent_confidence_score": _float_or_none(
            _first(state.get("latent_confidence_score"), latent.get("latent_confidence_score")),
            4,
        ),
        "validation_status": str(
            _first(latent.get("validation_status"), validation.get("validation_status"), default="")
        ),
        "validation_quality_pct": _ratio_to_pct(
            _first(state.get("validation_quality"), latent.get("validation_quality"))
        ),
        "validation_auc": _float_or_none(_get(validation, "auc"), 4),
        "top_decile_event_lift": _float_or_none(_get(validation, "lift_top_decile"), 4),
        "methodology_version": str(_get(alert, "methodology_version", default="")),
        "status": "ok",
        "error": "",
    }
