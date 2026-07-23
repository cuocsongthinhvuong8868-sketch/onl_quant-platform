"""Snapshot hook for LTMM liquidity transmission reports."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_LAKE


SOURCE_DIR = DATA_LAKE / "data_LTMM" / "sourse_raw"
KEY_OVERLAY_NAMES = {
    "FX offshore stress footprint",
    "Interbank line tightness proxy",
    "Equity-rate wedge",
    "VN30F basis pressure",
    "Fund system cash posture",
    "Foreign flow 5d pressure",
    "Margin call wave footprint",
}


def _parse_file_date(path: Path) -> dt.date | None:
    stem = path.stem
    if len(stem) != 8 or not stem.isdigit():
        return None
    try:
        return dt.datetime.strptime(stem, "%d%m%Y").date()
    except ValueError:
        return None


def _file_sort_key(path: Path) -> tuple[dt.date, float]:
    return (_parse_file_date(path) or dt.date.min, path.stat().st_mtime)


def _latest_source_json() -> Path:
    files = list(Path(SOURCE_DIR).glob("*.json"))
    if not files:
        raise FileNotFoundError(f"Missing LTMM source JSON in {SOURCE_DIR}")
    return max(files, key=_file_sort_key)


def _frame(payload: dict[str, Any], key: str) -> pd.DataFrame:
    value = payload.get(key)
    if isinstance(value, list):
        return pd.DataFrame(value)
    return pd.DataFrame()


def _row_by_index(latest: pd.DataFrame, index_name: str) -> pd.Series | None:
    if latest.empty or "index_name" not in latest.columns:
        return None
    rows = latest.loc[latest["index_name"].astype(str).eq(index_name)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except Exception:
        return True


def _float(row: pd.Series | None, key: str, digits: int = 4) -> float | None:
    if row is None or key not in row.index:
        return None
    value = row[key]
    if not _is_present(value):
        return None
    return round(float(value), digits)


def _text(row: pd.Series | None, key: str, default: str = "") -> str:
    if row is None or key not in row.index:
        return default
    value = row[key]
    if not _is_present(value):
        return default
    return str(value)


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _index_value(latest: pd.DataFrame, index_name: str) -> float | None:
    return _float(_row_by_index(latest, index_name), "index_value")


def _fire_triggers(triggers: pd.DataFrame) -> pd.DataFrame:
    if triggers.empty or "signal_state" not in triggers.columns:
        return pd.DataFrame()
    return triggers.loc[triggers["signal_state"].astype(str).str.upper().eq("FIRE")].copy()


def _summary_state(latest: pd.DataFrame, triggers: pd.DataFrame) -> str:
    if len(_fire_triggers(triggers)) > 0:
        return "ALERT"
    fli_value = _index_value(latest, "FLI")
    mli_value = _index_value(latest, "MLI")
    if fli_value is not None and mli_value is not None and fli_value >= 0.75 and mli_value >= 0.75:
        return "FUNDING STRESS TRANSMITTING"
    if fli_value is not None and fli_value >= 0.75:
        return "UPSTREAM TIGHTENING"
    if mli_value is not None and mli_value >= 0.75:
        return "MARKET LIQUIDITY STRESS"
    return "MONITOR"


def _near_fire_triggers(triggers: pd.DataFrame, fire_triggers: pd.DataFrame) -> pd.DataFrame:
    if triggers.empty or not {"fresh_conditions_met", "fresh_conditions_total"}.issubset(
        triggers.columns
    ):
        return pd.DataFrame()
    totals = _numeric_column(triggers, "fresh_conditions_total")
    met = _numeric_column(triggers, "fresh_conditions_met")
    return triggers.loc[
        ~triggers.index.isin(fire_triggers.index)
        & (totals > 0)
        & (met >= totals - 1)
    ].copy()


def _sort_by_stress(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "stress_score" not in frame.columns:
        return pd.DataFrame()
    ordered = frame.copy()
    ordered["stress_score"] = pd.to_numeric(ordered["stress_score"], errors="coerce")
    return ordered.dropna(subset=["stress_score"]).sort_values("stress_score", ascending=False)


def _first_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    return frame.iloc[0]


def _snapshot_date(latest: pd.DataFrame, source_path: Path) -> str:
    if not latest.empty and "as_of_date" in latest.columns:
        parsed = pd.to_datetime(latest["as_of_date"], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.max().strftime("%Y-%m-%d")
    source_date = _parse_file_date(source_path)
    if source_date:
        return source_date.isoformat()
    return source_path.stem


def _transmission_gap_state(gap: float | None) -> str:
    if gap is None:
        return ""
    if gap >= 0.75:
        return "downstream_materially_tighter"
    if abs(gap) >= 0.5:
        return "meaningful_transmission_gap"
    return "contained_gap"


def snapshot(df_close=None, load_custom=None) -> dict:
    source_path = _latest_source_json()
    payload = json.loads(source_path.read_text(encoding="utf-8"))

    latest = _frame(payload, "latest_indices")
    bottlenecks = _sort_by_stress(_frame(payload, "bottlenecks"))
    overlays = _frame(payload, "overlays")
    triggers = _frame(payload, "triggers")

    if latest.empty:
        raise ValueError(f"LTMM source JSON has no latest_indices: {source_path}")

    fire = _fire_triggers(triggers)
    near_fire = _near_fire_triggers(triggers, fire)
    key_overlays = pd.DataFrame()
    if not overlays.empty and "overlay" in overlays.columns:
        key_overlays = _sort_by_stress(
            overlays.loc[overlays["overlay"].astype(str).isin(KEY_OVERLAY_NAMES)].copy()
        )

    fli = _row_by_index(latest, "FLI")
    mli = _row_by_index(latest, "MLI")
    te = _row_by_index(latest, "TE")
    fri_collateral = _row_by_index(latest, "FRI_collateral")
    fri_risk = _row_by_index(latest, "FRI_risk")
    fli_value = _float(fli, "index_value")
    mli_value = _float(mli, "index_value")
    transmission_gap = (
        round(mli_value - fli_value, 4)
        if fli_value is not None and mli_value is not None
        else None
    )
    primary_bottleneck = _first_row(bottlenecks)
    strongest_overlay = _first_row(key_overlays)
    excluded_conditions = (
        int(_numeric_column(triggers, "conditions_excluded").fillna(0).sum())
        if not triggers.empty
        else 0
    )

    return {
        "snapshot_date": _snapshot_date(latest, source_path),
        "source_file": source_path.name,
        "headline_state": _summary_state(latest, triggers),
        "fli": fli_value,
        "fli_state": _text(fli, "state"),
        "fli_quality_score": _float(fli, "quality_score"),
        "fli_quality_state": _text(fli, "quality_state"),
        "mli": mli_value,
        "mli_state": _text(mli, "state"),
        "mli_quality_score": _float(mli, "quality_score"),
        "mli_quality_state": _text(mli, "quality_state"),
        "te": _float(te, "index_value"),
        "te_state": _text(te, "state"),
        "te_quality_score": _float(te, "quality_score"),
        "fri_collateral": _float(fri_collateral, "index_value"),
        "fri_collateral_state": _text(fri_collateral, "state"),
        "fri_collateral_quality_state": _text(fri_collateral, "quality_state"),
        "fri_risk": _float(fri_risk, "index_value"),
        "fri_risk_state": _text(fri_risk, "state"),
        "transmission_gap": transmission_gap,
        "transmission_gap_state": _transmission_gap_state(transmission_gap),
        "fire_trigger_count": int(len(fire)),
        "near_fire_trigger_count": int(len(near_fire)),
        "transmission_breakdown_fire": (
            bool(fire["trigger_id"].astype(str).eq("transmission_breakdown").any())
            if "trigger_id" in fire.columns
            else False
        ),
        "excluded_condition_count": excluded_conditions,
        "top_fire_trigger_id": _text(_first_row(fire), "trigger_id"),
        "top_near_fire_trigger_id": _text(_first_row(near_fire), "trigger_id"),
        "primary_bottleneck": _text(primary_bottleneck, "constraint"),
        "primary_bottleneck_layer": _text(primary_bottleneck, "layer"),
        "primary_bottleneck_stress_score": _float(primary_bottleneck, "stress_score"),
        "primary_bottleneck_state": _text(primary_bottleneck, "state"),
        "primary_bottleneck_quality": _text(primary_bottleneck, "quality"),
        "primary_bottleneck_observation_date": _text(primary_bottleneck, "observation_date"),
        "strongest_key_overlay": _text(strongest_overlay, "overlay"),
        "strongest_key_overlay_node": _text(strongest_overlay, "node"),
        "strongest_key_overlay_stress_score": _float(strongest_overlay, "stress_score"),
        "strongest_key_overlay_state": _text(strongest_overlay, "state"),
        "key_overlay_count": int(len(key_overlays)),
        "status": "ok",
        "error": "",
    }
