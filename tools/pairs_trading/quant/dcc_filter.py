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
    _dcc_q_recursion,
    _ewma_correlation,
    _ewma_pair_correlation_series,
    fit_dcc,
    pair_correlation,
)

logger = logging.getLogger(__name__)


def prices_to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Log-returns consumed by DCC functions. NaN-tolerant per-column."""
    numeric = prices.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric = numeric.where(numeric > 0)
    return np.log(numeric).diff().replace([np.inf, -np.inf], np.nan).dropna(how="all")


def pair_rho_result(
    prices: pd.DataFrame,
    t1: str,
    t2: str,
    method: str = "ewma",
) -> dict:
    """Correlation series plus the method actually used and diagnostics."""
    if t1 not in prices.columns or t2 not in prices.columns:
        return {"series": pd.Series(dtype=float), "rho_now": float("nan"),
                "requested_method": method, "actual_method": "none", "warning": "missing ticker"}
    rets = prices_to_returns(prices[[t1, t2]]).dropna(how="any")
    if len(rets) < 30:
        return {"series": pd.Series(dtype=float), "rho_now": float("nan"),
                "requested_method": method, "actual_method": "none", "warning": "insufficient observations"}
    requested = str(method).lower()
    if requested not in {"ewma", "dcc"}:
        raise ValueError(f"rho method không hợp lệ: {requested}")
    actual = requested
    warning = ""
    try:
        if requested == "dcc":
            fit = fit_dcc(rets[[t1, t2]])
            if fit.get("converged", False):
                q_path = _dcc_q_recursion(
                    fit["std_resid"].to_numpy(), fit["alpha"], fit["beta"], fit["Q_bar"]
                )
                rho_values = q_path[:, 0, 1] / np.sqrt(q_path[:, 0, 0] * q_path[:, 1, 1])
                series = pd.Series(
                    np.clip(rho_values, -1.0, 1.0),
                    index=fit["std_resid"].index,
                    name=f"rho_{t1}_{t2}",
                )
            else:
                actual = "ewma"
                warning = "DCC did not converge; EWMA fallback used"
                series = _ewma_pair_correlation_series(rets, t1, t2)
        else:
            series = pair_correlation(rets, t1, t2, method="ewma")
        clean = series.dropna()
        return {
            "series": series,
            "rho_now": float(clean.iloc[-1]) if not clean.empty else float("nan"),
            "requested_method": requested,
            "actual_method": actual,
            "warning": warning,
        }
    except Exception as exc:
        logger.warning("pair_rho_result %s/%s fail: %s", t1, t2, exc)
        return {"series": pd.Series(dtype=float), "rho_now": float("nan"),
                "requested_method": requested, "actual_method": "none", "warning": str(exc)}


def pair_rho_now(prices: pd.DataFrame, t1: str, t2: str, method: str = "ewma") -> float:
    """Current ρ tại last date. method='ewma' cheap O(T); 'dcc' = 2-asset MLE chậm."""
    return float(pair_rho_result(prices, t1, t2, method)["rho_now"])


def pair_rho_series(prices: pd.DataFrame, t1: str, t2: str, method: str = "ewma") -> pd.Series:
    """Time-series ρ_t cho 1 pair (plot at Custom Pair tab)."""
    return pair_rho_result(prices, t1, t2, method)["series"]


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
