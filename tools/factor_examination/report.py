"""Snapshot hook for Portfolio Factor Examination reports."""
from __future__ import annotations

from typing import Any

import pandas as pd

from shared.data_loader import (
    load_close_prices,
    load_custom,
    load_ticker_metadata,
    load_volumes,
)
from tools.factor_examination.quant.factors import FACTOR_NAMES, compute_all_factors
from tools.factor_examination.quant.scoring import build_score_table


EXCLUDE_PATTERNS = ("FUEV", "FUET", "E1VFVN30", "VN30F")
MIN_ADV_BILLION = 1.0
SECTOR_NEUTRAL = True


def _build_universe(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    min_adv_billion: float = MIN_ADV_BILLION,
) -> list[str]:
    columns = [
        column
        for column in prices.columns
        if not any(str(column).startswith(pattern) for pattern in EXCLUDE_PATTERNS)
    ]
    if min_adv_billion <= 0 or len(prices) < 20:
        return columns
    dollar_volume = (prices[columns] * volumes[columns]).iloc[-20:]
    median_dv_billion = dollar_volume.median() / 1e6
    return median_dv_billion[median_dv_billion >= min_adv_billion].index.tolist()


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


def _safe_int(value: Any) -> int:
    if not _is_present(value):
        return 0
    return int(value)


def _factor_extreme(z_table: pd.DataFrame, ticker: str, ascending: bool) -> tuple[str, float | None]:
    if ticker not in z_table.index:
        return "", None
    row = z_table.loc[ticker].dropna().sort_values(ascending=ascending)
    if row.empty:
        return "", None
    return str(row.index[0]), _float_or_none(row.iloc[0], 4)


def _top_sector(sector_map: pd.Series, tickers: list[str]) -> str:
    if sector_map.empty or not tickers:
        return ""
    sector_counts = sector_map.reindex(tickers).dropna().astype(str).value_counts()
    if sector_counts.empty:
        return ""
    return str(sector_counts.index[0])


def snapshot(df_close=None, load_custom=None) -> dict:
    prices = df_close if df_close is not None else load_close_prices()
    volumes = load_volumes()
    if volumes is None:
        raise FileNotFoundError("market_volume.csv is required for factor examination report")

    common = prices.columns.intersection(volumes.columns)
    prices = prices[common].sort_index()
    volumes = volumes[common].reindex(prices.index)
    if prices.empty:
        raise ValueError("close price data is empty")

    custom_loader = load_custom or globals()["load_custom"]
    market = custom_loader("vnindex_cache.csv")["VNINDEX"].reindex(prices.index).ffill()
    metadata = load_ticker_metadata()
    universe = _build_universe(prices, volumes)
    if len(universe) < 30:
        raise ValueError(f"Factor universe has only {len(universe)} tickers (<30 minimum)")

    factors = compute_all_factors(prices[universe], volumes[universe], market)
    scored = build_score_table(factors, metadata, sector_neutral=SECTOR_NEUTRAL)
    composite = scored["composite"].dropna().sort_values(ascending=False)
    z_table = scored["z"]
    rank_pct = scored["rank_pct"]
    sector_map = scored["sector_map"]
    if composite.empty:
        raise ValueError("factor composite is empty")

    top_ticker = str(composite.index[0])
    weak_ticker = str(composite.index[-1])
    top_factor, top_factor_z = _factor_extreme(z_table, top_ticker, ascending=False)
    weak_factor, weak_factor_z = _factor_extreme(z_table, weak_ticker, ascending=True)
    decile_n = max(1, int(len(composite) * 0.1))

    return {
        "snapshot_date": prices.index[-1].strftime("%Y-%m-%d"),
        "sector_neutral": SECTOR_NEUTRAL,
        "min_adv_billion": MIN_ADV_BILLION,
        "universe_count": int(len(universe)),
        "valid_ticker_count": int(len(composite)),
        "factor_count": len(FACTOR_NAMES),
        "strong_count": int((composite >= 0.8).sum()),
        "neutral_count": int(((composite > -0.5) & (composite < 0.5)).sum()),
        "weak_count": int((composite <= -1.0).sum()),
        "composite_median_z": _float_or_none(composite.median(), 4),
        "composite_dispersion_z": _float_or_none(composite.std(), 4),
        "top_ticker": top_ticker,
        "top_composite_z": _float_or_none(composite.iloc[0], 4),
        "top_rank_pct": _float_or_none(rank_pct.get(top_ticker), 2),
        "top_sector": str(sector_map.get(top_ticker, "")),
        "top_factor": top_factor,
        "top_factor_z": top_factor_z,
        "weakest_ticker": weak_ticker,
        "weakest_composite_z": _float_or_none(composite.iloc[-1], 4),
        "weakest_rank_pct": _float_or_none(rank_pct.get(weak_ticker), 2),
        "weakest_sector": str(sector_map.get(weak_ticker, "")),
        "weakest_factor": weak_factor,
        "weakest_factor_z": weak_factor_z,
        "top_decile_sector": _top_sector(sector_map, list(composite.head(decile_n).index)),
        "bottom_decile_sector": _top_sector(sector_map, list(composite.tail(decile_n).index)),
        "metadata_available": metadata is not None and not metadata.empty,
        "status": "ok",
        "error": "",
    }
