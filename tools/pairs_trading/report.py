"""Snapshot hook for Pairs Trading Research Lab reports."""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from shared.data_loader import load_close_prices
from tools.pairs_trading.quant.clusters import PREDEFINED_CLUSTERS
from tools.pairs_trading.quant.cointegration import (
    HALF_LIFE_MAX,
    HALF_LIFE_MIN,
    engle_granger,
    johansen_test,
    ou_half_life_raw,
)
from tools.pairs_trading.quant.dcc_filter import prices_to_returns
from tools.pairs_trading.quant.signal import DEFAULT_ENTRY, DEFAULT_STOP, z_score_60d


MIN_OBS = 120
START_DATE = "2018-01-01"


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


def _pair_rho_60d(prices: pd.DataFrame, ticker_1: str, ticker_2: str) -> float | None:
    returns = prices_to_returns(prices[[ticker_1, ticker_2]]).dropna().tail(60)
    if len(returns) < 30:
        return None
    rho = returns[ticker_1].corr(returns[ticker_2])
    return _float_or_none(rho, 4) if np.isfinite(rho) else None


def _best_eg(prices: pd.DataFrame, ticker_1: str, ticker_2: str) -> dict[str, Any]:
    first = engle_granger(prices[ticker_1], prices[ticker_2])
    second = engle_granger(prices[ticker_2], prices[ticker_1])
    if float(second["p_value"]) < float(first["p_value"]):
        return {**second, "pair": f"{ticker_2}/{ticker_1}"}
    return {**first, "pair": f"{ticker_1}/{ticker_2}"}


def _signal_label(z_latest: float | None, tradable: bool) -> str:
    if z_latest is None:
        return "NO_Z_SCORE"
    if abs(z_latest) > DEFAULT_STOP:
        return "QUARANTINE"
    if not tradable:
        return "MONITOR"
    if z_latest >= DEFAULT_ENTRY:
        return "ENTRY_SHORT_SPREAD"
    if z_latest <= -DEFAULT_ENTRY:
        return "ENTRY_LONG_SPREAD"
    return "MONITOR"


def _scan_pair(prices: pd.DataFrame, cluster: str, ticker_1: str, ticker_2: str) -> dict[str, Any] | None:
    pair_prices = prices[[ticker_1, ticker_2]].dropna().loc[START_DATE:]
    if len(pair_prices) < MIN_OBS:
        return None
    eg = _best_eg(pair_prices, ticker_1, ticker_2)
    half_life = _float_or_none(ou_half_life_raw(eg["resid"]), 2)
    z_series = z_score_60d(eg["resid"]).dropna()
    z_latest = _float_or_none(z_series.iloc[-1], 4) if not z_series.empty else None
    p_value = _float_or_none(eg.get("p_value"), 6)
    cointegrated = bool(p_value is not None and p_value < 0.05)
    half_life_ok = bool(
        half_life is not None and HALF_LIFE_MIN <= half_life <= HALF_LIFE_MAX
    )
    tradable = cointegrated and half_life_ok

    return {
        "cluster": cluster,
        "pair": eg["pair"],
        "p_value": p_value,
        "beta": _float_or_none(eg.get("beta"), 4),
        "half_life": half_life,
        "half_life_ok": half_life_ok,
        "z_score": z_latest,
        "rho_60d": _pair_rho_60d(pair_prices, ticker_1, ticker_2),
        "cointegrated": cointegrated,
        "tradable": tradable,
        "signal": _signal_label(z_latest, tradable),
        "n_obs": int(eg.get("n_obs", len(pair_prices))),
    }


def _best_pair(pair_rows: list[dict[str, Any]]) -> dict[str, Any]:
    tradable = [row for row in pair_rows if row["tradable"]]
    candidates = tradable or [row for row in pair_rows if row["p_value"] is not None]
    if not candidates:
        return {}
    return sorted(candidates, key=lambda row: row["p_value"])[0]


def _cluster_johansen(prices: pd.DataFrame, cluster: str, tickers: list[str]) -> dict[str, Any]:
    cluster_prices = prices[tickers].dropna(how="any").loc[START_DATE:]
    if len(cluster_prices) < 100:
        return {
            "cluster": cluster,
            "available_ticker_count": len(tickers),
            "n_coint_vectors": 0,
            "johansen_status": "insufficient_obs",
        }
    result = johansen_test(cluster_prices)
    return {
        "cluster": cluster,
        "available_ticker_count": len(tickers),
        "n_coint_vectors": int(result.get("n_coint_vectors", 0)),
        "johansen_status": "ok",
    }


def snapshot(df_close=None, load_custom=None) -> dict:
    prices = (df_close if df_close is not None else load_close_prices()).sort_index()
    if prices.empty:
        raise ValueError("close price data is empty")

    available = set(prices.columns)
    cluster_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for cluster, configured_tickers in PREDEFINED_CLUSTERS.items():
        tickers = [ticker for ticker in configured_tickers if ticker in available]
        if len(tickers) < 2:
            continue
        cluster_rows.append(_cluster_johansen(prices, cluster, tickers))
        for ticker_1, ticker_2 in combinations(tickers, 2):
            row = _scan_pair(prices, cluster, ticker_1, ticker_2)
            if row is not None:
                pair_rows.append(row)

    if not pair_rows:
        raise ValueError("no pairs had enough observations for analysis")

    best = _best_pair(pair_rows)
    johansen_top = sorted(
        cluster_rows,
        key=lambda row: row["n_coint_vectors"],
        reverse=True,
    )[0] if cluster_rows else {}

    return {
        "snapshot_date": prices.index[-1].strftime("%Y-%m-%d"),
        "cluster_count": int(len(PREDEFINED_CLUSTERS)),
        "evaluated_cluster_count": int(len(cluster_rows)),
        "total_pair_count": int(len(pair_rows)),
        "cointegrated_pair_count": int(sum(row["cointegrated"] for row in pair_rows)),
        "tradable_pair_count": int(sum(row["tradable"] for row in pair_rows)),
        "quarantine_pair_count": int(sum(row["signal"] == "QUARANTINE" for row in pair_rows)),
        "entry_signal_count": int(sum(str(row["signal"]).startswith("ENTRY_") for row in pair_rows)),
        "best_cluster": str(best.get("cluster", "")),
        "best_pair": str(best.get("pair", "")),
        "best_p_value": best.get("p_value"),
        "best_beta": best.get("beta"),
        "best_half_life": best.get("half_life"),
        "best_z_score": best.get("z_score"),
        "best_rho_60d": best.get("rho_60d"),
        "best_signal": str(best.get("signal", "")),
        "top_johansen_cluster": str(johansen_top.get("cluster", "")),
        "top_johansen_coint_vectors": int(johansen_top.get("n_coint_vectors", 0)),
        "methodology": "predefined_cluster_scan_engle_granger_johansen_ou_zscore_v1",
        "status": "ok",
        "error": "",
    }
