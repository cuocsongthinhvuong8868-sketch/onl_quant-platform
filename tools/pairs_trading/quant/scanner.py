"""
scanner.py — Universe pair scanner cho Pairs Trading.

4-stage funnel để surface pair candidate từ ~245 mã universe → top 50 actionable:
  Stage 0: same industry_code + same exchange bucket (mặc định)
  Stage 1: Pearson ρ trailing 60d ≥ min_rho_screen (default 0.75)
  Stage 2: Engle-Granger ADF p < 0.05
  Stage 3: OU half-life ∈ [hl_min, hl_max]

Composite score = (1 - p_value) × ρ × hl_proximity_to_target để rank.

User flow: scanner surface candidate → click "Pre-fill Custom Pair" →
switch sang tab Custom Pair để validate sâu (EG + OU + Hurst + DCC + backtest).

Đây KHÔNG phải full signal generator — chỉ pre-screen để giảm 31k pair → ~10 candidate.
"""
from __future__ import annotations

import logging
from itertools import combinations

import numpy as np
import pandas as pd

from tools.pairs_trading.quant.cointegration import engle_granger, ou_half_life_raw
from tools.pairs_trading.quant.dcc_filter import prices_to_returns

logger = logging.getLogger(__name__)

DEFAULT_MIN_RHO_SCREEN = 0.75
DEFAULT_HL_TARGET = 15.0
MAX_OUTPUT_ROWS = 50
TICKER_METADATA_PATH = "data_lake/ticker_metadata.csv"


def load_ticker_metadata(path: str = TICKER_METADATA_PATH) -> pd.DataFrame:
    """Load industry_code/industry_name/exchange indexed by Ticker."""
    df = pd.read_csv(path).set_index("Ticker")
    required = {"industry_code", "exchange"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"ticker_metadata.csv thiếu columns: {missing}")
    return df


def candidate_pairs(
    metadata: pd.DataFrame,
    available_tickers: list[str],
    same_sector_only: bool = True,
    cross_exchange: bool = False,
) -> list[tuple[str, str]]:
    """Generate (t1, t2) tuples sau sector/exchange bucketing.

    same_sector_only=True + cross_exchange=False → group by (industry_code, exchange).
    Đây là default cho retail vì:
      - Same industry = economic linkage thật, giảm spurious cointegration
      - Same exchange = lock-step trading hours, FOL rules, lot size convention
    """
    universe = metadata.loc[metadata.index.intersection(available_tickers)]
    if universe.empty:
        return []

    if same_sector_only and not cross_exchange:
        group_cols: list[str] | str = ["industry_code", "exchange"]
    elif same_sector_only:
        group_cols = "industry_code"
    elif not cross_exchange:
        group_cols = "exchange"
    else:
        return list(combinations(universe.index.tolist(), 2))

    pairs: list[tuple[str, str]] = []
    for _, grp in universe.groupby(group_cols):
        if len(grp) >= 2:
            pairs.extend(combinations(sorted(grp.index.tolist()), 2))
    return pairs


def correlation_screen(
    prices: pd.DataFrame,
    pairs: list[tuple[str, str]],
    min_rho: float = DEFAULT_MIN_RHO_SCREEN,
    window: int = 60,
) -> list[tuple[str, str, float]]:
    """Trailing N-day Pearson ρ pre-screen. Cheap O(window) per pair.

    Returns list of (t1, t2, rho) với rho ≥ min_rho.
    Pair có <30 obs sau dropna sẽ skip (insufficient data).
    """
    rets = prices_to_returns(prices).tail(window * 3)  # buffer cho per-pair dropna
    survivors: list[tuple[str, str, float]] = []
    for t1, t2 in pairs:
        if t1 not in rets.columns or t2 not in rets.columns:
            continue
        sub = rets[[t1, t2]].dropna().tail(window)
        if len(sub) < 30:
            continue
        rho = float(sub[t1].corr(sub[t2]))
        if np.isfinite(rho) and rho >= min_rho:
            survivors.append((t1, t2, rho))
    return survivors


def _composite_score(p_value: float, rho: float, half_life: float, hl_target: float = DEFAULT_HL_TARGET) -> float:
    """Rank-friendly score: (1-p) × ρ × hl_proximity.

    hl_proximity = 1 khi hl == target, decay linear → 0.1 ở extremes.
    """
    hl_penalty = max(0.1, 1.0 - abs(half_life - hl_target) / 20.0)
    return (1.0 - p_value) * rho * hl_penalty


def run_universe_scan(prices: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Full 4-stage funnel. Returns DataFrame ranked by composite score (top 50).

    params dict cần có:
      min_rho_screen, hl_min, hl_max, same_sector_only, cross_exchange
    """
    try:
        metadata = load_ticker_metadata()
    except Exception as exc:
        logger.error("Cannot load ticker_metadata.csv: %s", exc)
        return pd.DataFrame()

    available = list(prices.columns)
    pairs = candidate_pairs(
        metadata, available,
        same_sector_only=params.get("same_sector_only", True),
        cross_exchange=params.get("cross_exchange", False),
    )
    logger.info("Scanner stage 0 (sector/exchange bucket): %d pair", len(pairs))
    if not pairs:
        return pd.DataFrame()

    min_rho = params.get("min_rho_screen", DEFAULT_MIN_RHO_SCREEN)
    survivors_corr = correlation_screen(prices, pairs, min_rho=min_rho)
    logger.info("Scanner stage 1 (ρ_60d ≥ %.2f): %d pair", min_rho, len(survivors_corr))
    if not survivors_corr:
        return pd.DataFrame()

    hl_min = params.get("hl_min", 5)
    hl_max = params.get("hl_max", 30)
    sub = prices.loc["2020-01-01":]

    rows = []
    for t1, t2, rho in survivors_corr:
        if t1 not in sub.columns or t2 not in sub.columns:
            continue
        pair_data = sub[[t1, t2]].dropna()
        if len(pair_data) < 120:
            continue
        try:
            eg = engle_granger(pair_data[t1], pair_data[t2])
            if not eg["is_cointegrated"]:
                continue
            hl = ou_half_life_raw(eg["resid"])
            if not np.isfinite(hl) or not (hl_min <= hl <= hl_max):
                continue
            industry = metadata.loc[t1, "industry_name"] if t1 in metadata.index else "?"
            exch1 = metadata.loc[t1, "exchange"] if t1 in metadata.index else "?"
            exch2 = metadata.loc[t2, "exchange"] if t2 in metadata.index else "?"
            score = _composite_score(eg["p_value"], rho, hl)
            rows.append({
                "pair": f"{t1}/{t2}",
                "industry": industry,
                "exch": exch1 if exch1 == exch2 else f"{exch1}/{exch2}",
                "ρ_60d": round(rho, 3),
                "p_value": round(eg["p_value"], 4),
                "half_life": round(hl, 1),
                "beta": round(eg["beta"], 4),
                "score": round(score, 4),
            })
        except Exception as exc:
            logger.debug("Scanner EG %s/%s fail: %s", t1, t2, exc)

    logger.info("Scanner stage 2-3 (EG + half-life filter): %d pair", len(rows))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("score", ascending=False).head(MAX_OUTPUT_ROWS)
    return df.reset_index(drop=True)
