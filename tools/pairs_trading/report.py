"""Snapshot hook backed by the canonical pairs-research engine."""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from shared.data_loader import load_close_prices
from tools.pairs_trading.quant.clusters import PREDEFINED_CLUSTERS
from tools.pairs_trading.quant.cointegration import (
    adjust_pvalues_fdr,
    engle_granger,
    johansen_test,
)
from tools.pairs_trading.quant.engine import (
    PairAnalysisResult,
    PairResearchConfig,
    analyze_pair,
)

MIN_OBS = 120
FORMATION_WINDOW = 504


def _signal_label(result: PairAnalysisResult) -> str:
    if not np.isfinite(result.z_latest):
        return "NO_Z_SCORE"
    if abs(result.z_latest) >= 3.0:
        return "QUARANTINE"
    if not result.eligible:
        return "MONITOR"
    if result.z_latest >= 2.0:
        return "ENTRY_SHORT_SPREAD"
    if result.z_latest <= -2.0:
        return "ENTRY_LONG_SPREAD"
    return "MONITOR"


def _configured_pairs(prices: pd.DataFrame) -> list[tuple[str, str, str]]:
    available = set(prices.columns)
    rows: list[tuple[str, str, str]] = []
    for cluster, configured in PREDEFINED_CLUSTERS.items():
        tickers = [ticker for ticker in configured if ticker in available]
        rows.extend((cluster, t1, t2) for t1, t2 in combinations(tickers, 2))
    return rows


def _cluster_rows(prices: pd.DataFrame) -> list[dict]:
    available = set(prices.columns)
    rows: list[dict] = []
    for cluster, configured in PREDEFINED_CLUSTERS.items():
        tickers = [ticker for ticker in configured if ticker in available]
        if len(tickers) < 2:
            continue
        cluster_prices = prices[tickers].dropna(how="any").tail(FORMATION_WINDOW)
        if len(cluster_prices) < 100:
            rows.append(
                {
                    "cluster": cluster,
                    "available_ticker_count": len(tickers),
                    "n_coint_vectors": 0,
                    "johansen_status": "insufficient_obs",
                }
            )
            continue
        try:
            result = johansen_test(cluster_prices)
            rows.append(
                {
                    "cluster": cluster,
                    "available_ticker_count": len(tickers),
                    "n_coint_vectors": int(result["n_coint_vectors"]),
                    "johansen_status": "ok" if result["valid_system"] else "invalid_assumptions",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "cluster": cluster,
                    "available_ticker_count": len(tickers),
                    "n_coint_vectors": 0,
                    "johansen_status": f"error:{type(exc).__name__}",
                }
            )
    return rows


def snapshot(df_close=None, load_custom=None) -> dict:
    del load_custom
    prices = (df_close if df_close is not None else load_close_prices()).sort_index()
    if prices.empty:
        raise ValueError("close price data is empty")
    configured_pairs = _configured_pairs(prices)
    preliminary: list[tuple[str, str, str, float]] = []
    for cluster, t1, t2 in configured_pairs:
        pair = prices[[t1, t2]].dropna(how="any").tail(FORMATION_WINDOW)
        if len(pair) < MIN_OBS:
            continue
        try:
            preliminary.append((cluster, t1, t2, float(engle_granger(pair[t1], pair[t2])["p_value"])))
        except Exception:
            continue
    if not preliminary:
        raise ValueError("no pairs had enough observations for analysis")
    _, q_values = adjust_pvalues_fdr([row[3] for row in preliminary], alpha=0.05)
    cfg = PairResearchConfig(formation_window=FORMATION_WINDOW, require_stability=True)
    pair_rows: list[dict] = []
    for (cluster, t1, t2, _), q_value in zip(preliminary, q_values):
        try:
            result = analyze_pair(prices, t1, t2, cfg, q_value=float(q_value))
        except Exception:
            continue
        record = result.to_record()
        record["cluster"] = cluster
        record["signal"] = _signal_label(result)
        pair_rows.append(record)
    if not pair_rows:
        raise ValueError("all pair analyses failed")
    eligible = [row for row in pair_rows if row["eligible"]]
    best = min(eligible or pair_rows, key=lambda row: row["q_value"])
    clusters = _cluster_rows(prices)
    top_cluster = max(clusters, key=lambda row: row["n_coint_vectors"], default={})
    return {
        "snapshot_date": prices.index[-1].strftime("%Y-%m-%d"),
        "cluster_count": int(len(PREDEFINED_CLUSTERS)),
        "evaluated_cluster_count": int(len(clusters)),
        "total_pair_count": int(len(pair_rows)),
        "cointegrated_pair_count": int(sum(row["q_value"] < 0.05 and row["i1_valid"] for row in pair_rows)),
        "tradable_pair_count": int(sum(row["eligible"] for row in pair_rows)),
        "quarantine_pair_count": int(sum(row["signal"] == "QUARANTINE" for row in pair_rows)),
        "entry_signal_count": int(sum(str(row["signal"]).startswith("ENTRY_") for row in pair_rows)),
        "best_cluster": str(best.get("cluster", "")),
        "best_pair": str(best.get("pair", "")),
        "best_p_value": best.get("p_value"),
        "best_q_value": best.get("q_value"),
        "best_beta": best.get("beta"),
        "best_half_life": best.get("half_life"),
        "best_z_score": best.get("z_score"),
        "best_rho_60d": best.get("rho_now"),
        "best_signal": str(best.get("signal", "")),
        "top_johansen_cluster": str(top_cluster.get("cluster", "")),
        "top_johansen_coint_vectors": int(top_cluster.get("n_coint_vectors", 0)),
        "methodology": "pairs_research_point_in_time_fdr_v2",
        "methodology_version": "pairs_research_point_in_time_fdr_v2",
        "status": "ok",
        "error": "",
    }
