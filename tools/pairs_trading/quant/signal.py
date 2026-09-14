"""Causal z-scores and a quarantine-aware pairs signal state machine."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_Z_WINDOW = 60
DEFAULT_ENTRY = 2.0
DEFAULT_STOP = 3.0
DEFAULT_QUARANTINE_DAYS = 60  # Backward-compatible name; interpreted as sessions.


def z_score_60d(
    spread: pd.Series,
    window: int = DEFAULT_Z_WINDOW,
    *,
    method: str = "standard",
    lagged: bool = True,
) -> pd.Series:
    """Causal rolling z-score.

    With ``lagged=True`` (default), the location and scale used at t are based
    only on observations through t-1. ``robust`` uses median/MAD and ``ewma``
    uses exponentially weighted moments.
    """
    values = pd.to_numeric(spread, errors="coerce").replace([np.inf, -np.inf], np.nan)
    history = values.shift(1) if lagged else values
    method = str(method).lower()
    if method == "robust":
        center = history.rolling(window, min_periods=window).median()
        mad = history.rolling(window, min_periods=window).apply(
            lambda x: np.median(np.abs(x - np.median(x))), raw=True
        )
        scale = 1.4826 * mad
    elif method == "ewma":
        center = history.ewm(span=window, min_periods=window, adjust=False).mean()
        scale = history.ewm(span=window, min_periods=window, adjust=False).std()
    elif method == "standard":
        center = history.rolling(window, min_periods=window).mean()
        scale = history.rolling(window, min_periods=window).std()
    else:
        raise ValueError(f"z-score method không hợp lệ: {method}")
    return ((values - center) / scale.replace(0, np.nan)).rename("z_score")


def _value_at(value: float | pd.Series | None, index: pd.Index, i: int) -> float | None:
    if isinstance(value, pd.Series):
        selected = value.reindex(index).iloc[i]
        return float(selected) if pd.notna(selected) else None
    if value is None:
        return None
    return float(value)


def entry_exit_rules(
    z: pd.Series,
    entry: float = DEFAULT_ENTRY,
    exit_band: float = 0.0,
    stop: float = DEFAULT_STOP,
    half_life: Optional[float | pd.Series] = None,
    *,
    eligible: pd.Series | None = None,
    quarantine_bars: int = DEFAULT_QUARANTINE_DAYS,
    exit_on_ineligible: bool = True,
) -> pd.DataFrame:
    """Generate positions with hard stop-before-entry and session quarantine.

    ``eligible`` is a point-in-time gate (cointegration, stability, rho, data
    quality). It blocks new positions and, when ``exit_on_ineligible`` is true,
    closes an existing position at the first failed gate.
    """
    if not 0 <= exit_band < entry < stop:
        raise ValueError("Cần 0 <= exit_band < entry < stop")
    if quarantine_bars < 0:
        raise ValueError("quarantine_bars phải >= 0")
    values = pd.to_numeric(z, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    n = len(values)
    positions = np.zeros(n, dtype=int)
    entry_indices = np.full(n, -1, dtype=int)
    exit_reasons = [""] * n
    events = [""] * n
    quarantine_remaining = np.zeros(n, dtype=int)
    gate = eligible.reindex(values.index).fillna(False).astype(bool) if eligible is not None else pd.Series(True, index=values.index)

    state = 0
    entry_i = -1
    quarantine_until = -1
    for i, val in enumerate(values.to_numpy(dtype=float)):
        # A breakdown is always processed before an entry decision.
        if abs(val) >= stop:
            if state != 0:
                exit_reasons[i] = "stop_loss"
            events[i] = "breakdown"
            state = 0
            entry_i = -1
            quarantine_until = max(quarantine_until, i + quarantine_bars)
        elif state != 0:
            held = i - entry_i
            current_half_life = _value_at(half_life, values.index, i)
            time_stop = (
                int(np.ceil(2 * current_half_life))
                if current_half_life is not None and np.isfinite(current_half_life) and current_half_life > 0
                else None
            )
            if exit_on_ineligible and not bool(gate.iloc[i]):
                exit_reasons[i] = "eligibility_break"
                state, entry_i = 0, -1
            elif state > 0 and val >= -exit_band:
                exit_reasons[i] = "mean_revert"
                state, entry_i = 0, -1
            elif state < 0 and val <= exit_band:
                exit_reasons[i] = "mean_revert"
                state, entry_i = 0, -1
            elif time_stop is not None and held >= time_stop:
                exit_reasons[i] = "time_stop"
                state, entry_i = 0, -1

        can_enter = state == 0 and i > quarantine_until and bool(gate.iloc[i]) and not exit_reasons[i]
        if can_enter:
            if -stop < val <= -entry:
                state, entry_i, events[i] = 1, i, "entry"
            elif entry <= val < stop:
                state, entry_i, events[i] = -1, i, "entry"

        positions[i] = state
        entry_indices[i] = entry_i
        quarantine_remaining[i] = max(0, quarantine_until - i + 1)

    entry_dates = np.where(
        entry_indices >= 0,
        values.index.values[np.maximum(entry_indices, 0)],
        np.datetime64("NaT"),
    )
    return pd.DataFrame(
        {
            "position": positions,
            "entry_date": pd.to_datetime(entry_dates),
            "exit_reason": exit_reasons,
            "event": events,
            "quarantine_remaining": quarantine_remaining,
            "eligible": gate.to_numpy(dtype=bool),
        },
        index=values.index,
    )


def quarantine_flag(
    z_history: pd.Series,
    stop: float = DEFAULT_STOP,
    days: int = DEFAULT_QUARANTINE_DAYS,
) -> Optional[pd.Timestamp]:
    """Return the estimated end of a trading-session quarantine, or ``None``."""
    values = pd.to_numeric(z_history, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return None
    breach_positions = np.flatnonzero(values.abs().to_numpy() >= stop)
    if len(breach_positions) == 0:
        return None
    last_position = int(breach_positions[-1])
    elapsed_sessions = len(values) - 1 - last_position
    if elapsed_sessions >= days:
        return None
    remaining = days - elapsed_sessions
    return pd.Timestamp(values.index[-1]) + pd.offsets.BDay(remaining)


def detect_breakout(z: pd.Series, stop: float = DEFAULT_STOP) -> pd.Series:
    return (z.abs() >= stop).fillna(False).astype(bool)
