"""
dcc_filter.py — DCC correlation filter cho Pairs Trading.

Wrap shared.dcc_garch utilities cho pairs-trading-specific use:
- Compute current ρ_now cho 1 pair (EWMA fast path mặc định)
- Time-series ρ_t cho plot ở Custom Pair tab
- NxN current correlation matrix cho cluster heatmap
- Boolean filter `passes_rho_filter()` áp dụng vào Aggregate Backtest + Live Signals

Pairs trading thường require:
- Cointegration (long-run equilibrium) — đã có via EG/Johansen
- High recent correlation (short-run co-movement) — DCC filter này

Pair "decoupling" khi ρ_t drop từ historical level → SKIP entry mới
ngay cả khi cointegration test pass (regime break không kịp reflect vào EG p-value).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from shared.dcc_garch import (
    _ewma_correlation,
    pair_correlation,
)

logger = logging.getLogger(__name__)


def prices_to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Log-returns consumed by DCC functions. NaN-tolerant per-column."""
    return np.log(prices).diff().dropna(how="all")


def pair_rho_now(prices: pd.DataFrame, t1: str, t2: str, method: str = "ewma") -> float:
    """Current ρ tại last date. method='ewma' cheap O(T); 'dcc' = 2-asset MLE chậm."""
    if t1 not in prices.columns or t2 not in prices.columns:
        return float("nan")
    rets = prices_to_returns(prices[[t1, t2]]).dropna(how="any")
    if len(rets) < 30:
        return float("nan")
    try:
        rho_series = pair_correlation(rets, t1, t2, method=method)
        clean = rho_series.dropna()
        return float(clean.iloc[-1]) if not clean.empty else float("nan")
    except Exception as exc:
        logger.warning("pair_rho_now %s/%s fail: %s", t1, t2, exc)
        return float("nan")


def pair_rho_series(prices: pd.DataFrame, t1: str, t2: str, method: str = "ewma") -> pd.Series:
    """Time-series ρ_t cho 1 pair (plot at Custom Pair tab)."""
    if t1 not in prices.columns or t2 not in prices.columns:
        return pd.Series(dtype=float, name=f"rho_{t1}_{t2}")
    rets = prices_to_returns(prices[[t1, t2]]).dropna(how="any")
    if len(rets) < 30:
        return pd.Series(dtype=float, name=f"rho_{t1}_{t2}")
    try:
        return pair_correlation(rets, t1, t2, method=method)
    except Exception as exc:
        logger.warning("pair_rho_series %s/%s fail: %s", t1, t2, exc)
        return pd.Series(dtype=float, name=f"rho_{t1}_{t2}")


def cluster_rho_matrix(prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """NxN current correlation matrix cho cluster (EWMA path, cheap)."""
    available = [t for t in tickers if t in prices.columns]
    if len(available) < 2:
        return pd.DataFrame()
    rets = prices_to_returns(prices[available]).dropna(how="any")
    if len(rets) < 30:
        return pd.DataFrame()
    try:
        return _ewma_correlation(rets)
    except Exception as exc:
        logger.warning("cluster_rho_matrix fail: %s", exc)
        return pd.DataFrame()


def passes_rho_filter(rho_now: float, min_rho: float) -> bool:
    """True nếu pair pass filter. NaN → fail (conservative)."""
    if not np.isfinite(rho_now):
        return False
    return rho_now >= min_rho
