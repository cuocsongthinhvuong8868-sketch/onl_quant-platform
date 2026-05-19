"""
signal.py — Z-score 60d + entry/exit rule + quarantine flag.

Spec §13.3:
- Entry: |z| > 2 (long low-leg, short high-leg)
- Exit: z crosses 0 hoặc time-stop 2× half-life
- Stop: |z| > 3 → cointegration breakdown → quarantine pair 60 phiên
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_Z_WINDOW = 60
DEFAULT_ENTRY = 2.0
DEFAULT_STOP = 3.0
DEFAULT_QUARANTINE_DAYS = 60


def z_score_60d(spread: pd.Series, window: int = DEFAULT_Z_WINDOW) -> pd.Series:
    """Rolling z-score: (spread - mean_w) / std_w.

    Window default 60d theo spec §13.3.
    """
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    z = (spread - mean) / std.replace(0, np.nan)
    return z.rename("z_score")


def entry_exit_rules(
    z: pd.Series,
    entry: float = DEFAULT_ENTRY,
    exit_band: float = 0.0,
    stop: float = DEFAULT_STOP,
    half_life: Optional[float] = None,
) -> pd.DataFrame:
    """Generate position track từ z-series.

    State machine:
      flat → (z < -entry) → long_spread (long P1, short β·P2)
      flat → (z > +entry) → short_spread
      long_spread → (z >= exit_band) → flat
      short_spread → (z <= exit_band) → flat
      ANY → (|z| > stop) → flat + flag quarantine
      ANY → (bars_held >= 2·half_life) → flat (time stop)

    Returns DataFrame index=z.index, cols:
      position     : -1/0/+1 (vs spread convention: +1 = long spread = long P1)
      entry_date   : NaT khi flat, ngày vào lệnh khi position != 0
      exit_reason  : "" | "mean_revert" | "stop_loss" | "time_stop" tại điểm exit
    """
    z = z.dropna()
    n = len(z)
    position = np.zeros(n, dtype=int)
    entry_idx = np.full(n, -1, dtype=int)
    exit_reason = [""] * n

    state = 0  # 0=flat, +1=long spread, -1=short spread
    entry_i = -1
    time_stop_bars: Optional[int] = None
    if half_life is not None and np.isfinite(half_life):
        time_stop_bars = int(2 * half_life)

    for i, val in enumerate(z.values):
        if state != 0:
            bars_held = i - entry_i
            if abs(val) > stop:
                exit_reason[i] = "stop_loss"
                state = 0
                entry_i = -1
            elif state > 0 and val >= exit_band:
                exit_reason[i] = "mean_revert"
                state = 0
                entry_i = -1
            elif state < 0 and val <= exit_band:
                exit_reason[i] = "mean_revert"
                state = 0
                entry_i = -1
            elif time_stop_bars and bars_held >= time_stop_bars:
                exit_reason[i] = "time_stop"
                state = 0
                entry_i = -1

        if state == 0 and exit_reason[i] == "":
            if val < -entry:
                state = +1
                entry_i = i
            elif val > +entry:
                state = -1
                entry_i = i

        position[i] = state
        entry_idx[i] = entry_i

    entry_dates = np.where(entry_idx >= 0, z.index.values[entry_idx], np.datetime64("NaT"))
    return pd.DataFrame(
        {
            "position": position,
            "entry_date": pd.to_datetime(entry_dates),
            "exit_reason": exit_reason,
        },
        index=z.index,
    )


def quarantine_flag(
    z_history: pd.Series,
    stop: float = DEFAULT_STOP,
    days: int = DEFAULT_QUARANTINE_DAYS,
) -> Optional[pd.Timestamp]:
    """Detect khi pair bị quarantine. Returns ngày kết thúc quarantine HOẶC None.

    Trigger: |z| > stop trong N ngày gần đây.
    Pair sẽ bị block trade cho tới ngày trả về.
    """
    z = z_history.dropna()
    if z.empty:
        return None
    breach_mask = z.abs() > stop
    if not breach_mask.any():
        return None
    last_breach = z.index[breach_mask][-1]
    return pd.Timestamp(last_breach) + pd.Timedelta(days=days)


def detect_breakout(z: pd.Series, stop: float = DEFAULT_STOP) -> pd.Series:
    """Bool series: True khi |z| > stop (point-wise breakout signal)."""
    return (z.abs() > stop).fillna(False).astype(bool)
