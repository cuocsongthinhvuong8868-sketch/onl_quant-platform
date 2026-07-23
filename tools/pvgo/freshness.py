"""Market-session freshness checks for the PVGO valuation feed."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from config import DATA_LAKE

DEFAULT_MARKET_DATA_PATH = DATA_LAKE / "vnindex_cache.csv"
DEFAULT_MAX_SESSION_LAG = 0

FreshnessResult = dict[str, str | int | None]


def _coerce_date(value: Any) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _normalize_market_dates(values: Iterable[Any] | pd.Series | pd.Index) -> pd.DatetimeIndex:
    normalized = [timestamp for value in values if (timestamp := _coerce_date(value)) is not None]
    if not normalized:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(normalized).drop_duplicates().sort_values()


def load_market_dates(path: str | Path = DEFAULT_MARKET_DATA_PATH) -> pd.DatetimeIndex:
    """Load canonical VN-Index session dates from a market-data CSV."""
    path = Path(path)
    if not path.exists():
        return pd.DatetimeIndex([])

    try:
        market_data = pd.read_csv(path)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError):
        return pd.DatetimeIndex([])
    if market_data.empty:
        return pd.DatetimeIndex([])

    columns = {str(column).strip().lower(): column for column in market_data.columns}
    date_column = next(
        (columns[name] for name in ("time", "date", "trading_date") if name in columns),
        None,
    )
    if date_column is None:
        return pd.DatetimeIndex([])
    return _normalize_market_dates(market_data[date_column])


def evaluate_freshness(
    source_date: str | date | datetime | pd.Timestamp | None,
    market_dates: Iterable[Any] | pd.Series | pd.Index,
    max_session_lag: int = DEFAULT_MAX_SESSION_LAG,
) -> FreshnessResult:
    """Evaluate source freshness by counting later observed market sessions."""
    if max_session_lag < 0:
        raise ValueError("max_session_lag must be non-negative")

    source_timestamp = _coerce_date(source_date)
    sessions = _normalize_market_dates(market_dates)
    result: FreshnessResult = {
        "status": "UNKNOWN",
        "source_date": source_timestamp.strftime("%Y-%m-%d") if source_timestamp is not None else None,
        "market_date": sessions[-1].strftime("%Y-%m-%d") if len(sessions) else None,
        "session_lag": None,
        "max_session_lag": int(max_session_lag),
    }
    if source_timestamp is None or sessions.empty:
        return result

    session_lag = int((sessions > source_timestamp).sum())
    result["session_lag"] = session_lag
    result["status"] = "CURRENT" if session_lag <= max_session_lag else "STALE"
    return result


def evaluate_pvgo_freshness(
    source_date: str | date | datetime | pd.Timestamp | None,
    market_dates: Iterable[Any] | pd.Series | pd.Index | None = None,
    *,
    market_data_path: str | Path = DEFAULT_MARKET_DATA_PATH,
    max_session_lag: int = DEFAULT_MAX_SESSION_LAG,
) -> FreshnessResult:
    """Evaluate PVGO freshness, loading canonical market sessions when omitted."""
    sessions = load_market_dates(market_data_path) if market_dates is None else market_dates
    return evaluate_freshness(source_date, sessions, max_session_lag=max_session_lag)
