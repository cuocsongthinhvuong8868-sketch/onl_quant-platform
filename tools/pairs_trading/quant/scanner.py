"""
scanner.py — Universe pair scanner cho Pairs Trading.

Point-in-time funnel để surface pair candidate từ universe → top 50 research candidates:
  Stage 0: same industry_code + same exchange bucket (mặc định)
  Stage 1: Pearson ρ trailing 60d ≥ min_rho_screen (default 0.75)
  Stage 2: proper Engle-Granger + I(1), then BH-FDR across all survivors
  Stage 3: exact AR(1) half-life + beta stability + ADV capacity

Composite score blends q-value strength, beta stability, correlation,
half-life proximity and liquidity capacity.

User flow: scanner surface candidate → click "Pre-fill Custom Pair" →
switch sang tab Custom Pair để validate sâu và chạy walk-forward backtest.

Đây KHÔNG phải full signal generator — chỉ pre-screen để giảm 31k pair → ~10 candidate.
"""
from __future__ import annotations

import hashlib
import json
import logging
from itertools import combinations

import numpy as np
import pandas as pd

from shared.data_loader import load_ticker_metadata as load_shared_ticker_metadata, load_volumes
from tools.pairs_trading.quant.cointegration import (
    adjust_pvalues_fdr,
    beta_stability,
    engle_granger,
    ou_half_life_raw,
)
from tools.pairs_trading.quant.dcc_filter import prices_to_returns

logger = logging.getLogger(__name__)

DEFAULT_MIN_RHO_SCREEN = 0.75
DEFAULT_HL_TARGET = 15.0
MAX_OUTPUT_ROWS = 50
TICKER_METADATA_PATH = "data_lake/ticker_metadata.csv"


def load_ticker_metadata(path: str = TICKER_METADATA_PATH) -> pd.DataFrame:
    """Load industry_code/industry_name/exchange indexed by Ticker."""
    df = load_shared_ticker_metadata()
    if df is None:
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
    """Legacy-compatible score helper; scanner v2 additionally uses stability/liquidity.

    hl_proximity = 1 khi hl == target, decay linear → 0.1 ở extremes.
    """
    hl_penalty = max(0.1, 1.0 - abs(half_life - hl_target) / 20.0)
    return (1.0 - p_value) * rho * hl_penalty


def _adv_vnd(prices: pd.DataFrame, volumes: pd.DataFrame | None, ticker: str, window: int = 20) -> float:
    if volumes is None or ticker not in volumes or ticker not in prices:
        return float("nan")
    aligned = pd.concat(
        [prices[ticker].rename("price"), volumes[ticker].rename("volume")], axis=1
    ).replace([np.inf, -np.inf], np.nan).dropna().tail(window)
    aligned = aligned[(aligned["price"] > 0) & (aligned["volume"] > 0)]
    if aligned.empty:
        return float("nan")
    return float((aligned["price"] * 1_000.0 * aligned["volume"]).median())


def run_universe_scan(
    prices: pd.DataFrame,
    params: dict,
    *,
    volumes: pd.DataFrame | None = None,
    metadata: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Point-in-time screening funnel with FDR, stability and liquidity gates.

    params dict cần có:
      min_rho_screen, hl_min, hl_max, same_sector_only, cross_exchange
    """
    metadata = metadata if metadata is not None else load_ticker_metadata()
    clean_prices = prices.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean_prices = clean_prices.where(clean_prices > 0).sort_index()

    available = list(clean_prices.columns)
    pairs = candidate_pairs(
        metadata, available,
        same_sector_only=params.get("same_sector_only", True),
        cross_exchange=params.get("cross_exchange", False),
    )
    logger.info("Scanner stage 0 (sector/exchange bucket): %d pair", len(pairs))
    if not pairs:
        return pd.DataFrame()

    min_rho = params.get("min_rho_screen", DEFAULT_MIN_RHO_SCREEN)
    survivors_corr = correlation_screen(clean_prices, pairs, min_rho=min_rho)
    logger.info("Scanner stage 1 (ρ_60d ≥ %.2f): %d pair", min_rho, len(survivors_corr))
    if not survivors_corr:
        return pd.DataFrame()

    hl_min = float(params.get("hl_min", 5))
    hl_max = float(params.get("hl_max", 30))
    alpha = float(params.get("alpha", 0.05))
    formation_window = max(120, int(params.get("formation_window", 504)))
    min_adv_vnd = float(params.get("min_adv_vnd", 1_000_000_000))
    require_stability = bool(params.get("require_stability", True))
    sub = clean_prices.tail(formation_window)
    if volumes is None:
        try:
            volumes = load_volumes()
        except Exception:
            volumes = None

    rows = []
    for t1, t2, rho in survivors_corr:
        if t1 not in sub.columns or t2 not in sub.columns:
            continue
        pair_data = sub[[t1, t2]].dropna()
        if len(pair_data) < 120:
            continue
        try:
            eg = engle_granger(pair_data[t1], pair_data[t2], alpha=alpha)
            hl = ou_half_life_raw(eg["resid"])
            industry = metadata.loc[t1, "industry_name"] if t1 in metadata.index else "?"
            exch1 = metadata.loc[t1, "exchange"] if t1 in metadata.index else "?"
            exch2 = metadata.loc[t2, "exchange"] if t2 in metadata.index else "?"
            stability = beta_stability(pair_data, t1, t2, window=min(126, max(60, len(pair_data) // 2)))
            adv1 = _adv_vnd(clean_prices, volumes, t1)
            adv2 = _adv_vnd(clean_prices, volumes, t2)
            rows.append({
                "pair": f"{t1}/{t2}",
                "industry": industry,
                "exch": exch1 if exch1 == exch2 else f"{exch1}/{exch2}",
                "ρ_60d": round(rho, 3),
                "p_value": float(eg["p_value"]),
                "i1_valid": bool(eg["i1_valid"]),
                "half_life": float(hl),
                "beta": float(eg["beta"]),
                "stability_score": float(stability["score"]),
                "beta_stable": bool(stability["stable"]),
                "min_adv_vnd": float(min(adv1, adv2)) if np.isfinite(adv1) and np.isfinite(adv2) else float("nan"),
                "n_obs": int(eg["n_obs"]),
            })
        except Exception as exc:
            logger.debug("Scanner EG %s/%s fail: %s", t1, t2, exc)

    if not rows:
        return pd.DataFrame()
    tested = pd.DataFrame(rows)
    rejected, q_values = adjust_pvalues_fdr(tested["p_value"].to_numpy(), alpha=alpha)
    tested["q_value"] = q_values
    tested["fdr_pass"] = rejected
    tested["half_life_pass"] = tested["half_life"].between(hl_min, hl_max)
    tested["liquidity_pass"] = tested["min_adv_vnd"].ge(min_adv_vnd)
    tested["eligible"] = (
        tested["fdr_pass"]
        & tested["i1_valid"]
        & tested["beta"].gt(0)
        & tested["half_life_pass"]
        & tested["liquidity_pass"]
        & (tested["beta_stable"] if require_stability else True)
    )
    hl_proximity = (1.0 - (tested["half_life"] - DEFAULT_HL_TARGET).abs() / 30.0).clip(0.0, 1.0)
    statistical_strength = (-np.log10(tested["q_value"].clip(lower=1e-12)) / 4.0).clip(0.0, 1.0)
    rho_strength = tested["ρ_60d"].clip(lower=0.0, upper=1.0)
    liquidity_strength = (
        np.log10((tested["min_adv_vnd"] / max(min_adv_vnd, 1.0)).clip(lower=1.0)) / 2.0 + 0.5
    ).clip(0.0, 1.0)
    tested["score"] = (
        0.35 * statistical_strength
        + 0.25 * tested["stability_score"]
        + 0.20 * rho_strength
        + 0.10 * hl_proximity
        + 0.10 * liquidity_strength
    )
    output = tested[tested["eligible"]].sort_values("score", ascending=False).head(MAX_OUTPUT_ROWS).copy()
    fingerprint_payload = {
        key: params.get(key)
        for key in (
            "same_sector_only", "cross_exchange", "min_rho_screen", "hl_min", "hl_max",
            "formation_window", "min_adv_vnd", "require_stability",
        )
    }
    funnel = {
        "candidate_pairs": len(pairs),
        "correlation_pass": len(survivors_corr),
        "tested": len(tested),
        "fdr_pass": int(tested["fdr_pass"].sum()),
        "i1_pass": int(tested["i1_valid"].sum()),
        "half_life_pass": int(tested["half_life_pass"].sum()),
        "liquidity_pass": int(tested["liquidity_pass"].sum()),
        "eligible": int(tested["eligible"].sum()),
    }
    output.attrs["funnel"] = funnel
    output.attrs["tested"] = tested
    output.attrs["params_fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    output.attrs["methodology_version"] = "universe_scan_fdr_stability_liquidity_v2"
    logger.info("Scanner v2 funnel: %s", funnel)
    display_columns = [
        "pair", "industry", "exch", "ρ_60d", "p_value", "q_value", "half_life",
        "beta", "stability_score", "min_adv_vnd", "score",
    ]
    return output[display_columns].reset_index(drop=True)
