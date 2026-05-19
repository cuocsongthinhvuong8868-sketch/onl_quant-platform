"""
cointegration.py — Engle-Granger 2-step + Johansen + OU half-life + Hurst.

Cảnh báo (theo decision user 2026-05-19):
- Prices KHÔNG adjusted cho split/dividend. Spread có thể fake-break tại corp-action date.
  → Mitigation P1: warn user; P2 backlog: re-fetch với vnstock adjusted=True flag.

References:
- Engle & Granger (1987) — 2-step cointegration test
- Johansen (1991) — VECM + λ_max + trace stat
- Lo & MacKinlay (1988) — Hurst exponent variance ratio
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

logger = logging.getLogger(__name__)

# Spec §13.3: half-life filter 5-30 trading day
HALF_LIFE_MIN = 5
HALF_LIFE_MAX = 30

# ADF significance threshold cho EG residual stationarity
EG_PVALUE_THRESHOLD = 0.05


def engle_granger(p1: pd.Series, p2: pd.Series) -> dict:
    """Engle-Granger 2-step cointegration test.

    Step 1: OLS log(p1) = α + β·log(p2) + ε
    Step 2: ADF test trên residual ε (regression="nc" — no constant since OLS đã có intercept)

    Returns dict:
        beta, alpha          : OLS coefficients
        adf_stat, p_value    : ADF on residuals
        is_cointegrated      : p_value < 0.05
        resid                : residual Series (= spread)
        n_obs                : số observation sau align
    """
    s1 = np.log(p1.dropna())
    s2 = np.log(p2.dropna())
    aligned = pd.concat([s1, s2], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        raise ValueError(f"EG: cần ≥60 obs, có {len(aligned)}")

    y = aligned.iloc[:, 0].values
    x = aligned.iloc[:, 1].values

    # Step 1: OLS y = alpha + beta*x
    X = np.column_stack([np.ones_like(x), x])
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    alpha, beta = coefs
    resid_arr = y - (alpha + beta * x)
    resid = pd.Series(resid_arr, index=aligned.index, name="resid")

    # Step 2: ADF residual ("n" = no constant; residual đã mean-zero theo OLS)
    # statsmodels >=0.14 rename "nc" → "n"
    try:
        adf_result = adfuller(resid_arr, regression="n", autolag="AIC")
        adf_stat = float(adf_result[0])
        p_value = float(adf_result[1])
    except Exception as exc:
        logger.warning("ADF fail trên residual: %s", exc)
        adf_stat, p_value = float("nan"), 1.0

    return {
        "beta": float(beta),
        "alpha": float(alpha),
        "adf_stat": adf_stat,
        "p_value": p_value,
        "is_cointegrated": p_value < EG_PVALUE_THRESHOLD,
        "resid": resid,
        "n_obs": int(len(aligned)),
    }


def johansen_test(prices: pd.DataFrame, det_order: int = 0, k_ar_diff: int = 1) -> dict:
    """Johansen cointegration test cho cluster ≥2 ticker.

    Parameters
    ----------
    prices : DataFrame, columns=tickers
    det_order : -1 (no det), 0 (constant), 1 (linear trend). 0 cho equity log price
    k_ar_diff : số lag trong VECM difference. 1 = VAR(2)

    Returns dict:
        trace_stat       : (k,) trace statistics
        trace_crit_95    : (k,) critical values @ 95%
        n_coint_vectors  : số cointegrating relations (largest r với trace>crit)
        eig_vectors      : (k, n_coint) cointegrating vectors β
        tickers          : list[str]
    """
    df = np.log(prices.dropna(how="any"))
    if len(df) < 100:
        raise ValueError(f"Johansen: cần ≥100 obs sau dropna, có {len(df)}")
    if df.shape[1] < 2:
        raise ValueError("Johansen: cần ≥2 ticker")

    try:
        res = coint_johansen(df.values, det_order, k_ar_diff)
    except Exception as exc:
        raise RuntimeError(f"Johansen fit fail: {exc}") from exc

    trace_stat = np.asarray(res.lr1, dtype=float)
    trace_crit_95 = np.asarray(res.cvt[:, 1], dtype=float)  # cvt cols: 90/95/99
    # Decision rule: lớn nhất r mà trace_stat[r] > crit_95[r]
    n_coint = 0
    for i in range(len(trace_stat)):
        if trace_stat[i] > trace_crit_95[i]:
            n_coint = i + 1
        else:
            break

    return {
        "trace_stat": trace_stat,
        "trace_crit_95": trace_crit_95,
        "n_coint_vectors": int(n_coint),
        "eig_vectors": np.asarray(res.evec, dtype=float),
        "tickers": list(df.columns),
    }


def ou_half_life(spread: pd.Series) -> float:
    """OU half-life từ AR(1) fit của Δspread.

    Model: Δspread_t = θ·(μ − spread_{t-1}) + ε_t
    Half-life = ln(2) / θ.

    Returns NaN nếu:
      - θ ≤ 0 (không mean-revert)
      - hl ngoài [HALF_LIFE_MIN, HALF_LIFE_MAX] (5-30 ngày)
      - <60 obs

    Caller có thể bypass band check bằng `ou_half_life_raw(spread)`.
    """
    hl = ou_half_life_raw(spread)
    if not np.isfinite(hl):
        return float("nan")
    if hl < HALF_LIFE_MIN or hl > HALF_LIFE_MAX:
        logger.info("Half-life %.1f outside [%d, %d] → filter out", hl, HALF_LIFE_MIN, HALF_LIFE_MAX)
        return float("nan")
    return hl


def ou_half_life_raw(spread: pd.Series) -> float:
    """OU half-life không filter band — return raw value (or NaN nếu θ≤0)."""
    s = spread.dropna()
    if len(s) < 60:
        return float("nan")
    s_lag = s.shift(1).dropna()
    ds = s.diff().dropna()
    aligned = pd.concat([ds, s_lag], axis=1, join="inner").dropna()
    if len(aligned) < 30:
        return float("nan")
    y = aligned.iloc[:, 0].values
    x = aligned.iloc[:, 1].values
    # Δs = θ·(μ - s_lag) + ε  →  Δs = θμ - θ·s_lag + ε
    X = np.column_stack([np.ones_like(x), x])
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    neg_theta = coefs[1]  # = -θ
    theta = -neg_theta
    if theta <= 0:
        return float("nan")
    return float(np.log(2) / theta)


def hurst(spread: pd.Series, max_lag: int = 20) -> float:
    """Hurst exponent qua variance ratio.

    Var(spread[t+lag] - spread[t]) ~ lag^(2H).
    log-log regression slope = 2H. H<0.5 = anti-persistent (mean-reverting).
    """
    s = spread.dropna().values
    if len(s) < max_lag + 10:
        return float("nan")
    lags = np.arange(2, max_lag + 1)
    tau = np.array([np.std(s[lag:] - s[:-lag]) for lag in lags])
    if (tau <= 0).any():
        return float("nan")
    log_lag = np.log(lags)
    log_tau = np.log(tau)
    slope, _ = np.polyfit(log_lag, log_tau, 1)
    return float(slope)  # ≈ Hurst H (small lag approximation)


def pairwise_eg_matrix(prices: pd.DataFrame, tickers: Optional[list[str]] = None) -> pd.DataFrame:
    """NxN matrix p_value của Engle-Granger cho all pair trong cluster.

    Symmetric (run EG cả 2 chiều, lấy min p_value). Diagonal = 0.
    Output dùng cho Tab 2 "Pairwise Heatmap" (red < 0.05).
    """
    if tickers is None:
        tickers = list(prices.columns)
    n = len(tickers)
    M = pd.DataFrame(np.nan, index=tickers, columns=tickers)
    for i in range(n):
        M.iloc[i, i] = 0.0
        for j in range(i + 1, n):
            t1, t2 = tickers[i], tickers[j]
            try:
                eg_ab = engle_granger(prices[t1], prices[t2])
                eg_ba = engle_granger(prices[t2], prices[t1])
                p = min(eg_ab["p_value"], eg_ba["p_value"])
                M.iloc[i, j] = p
                M.iloc[j, i] = p
            except Exception as exc:
                logger.warning("EG fail %s/%s: %s", t1, t2, exc)
    return M
