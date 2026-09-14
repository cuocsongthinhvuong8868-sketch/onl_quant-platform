"""Cointegration and mean-reversion diagnostics for pairs trading.

The public functions keep the original dictionary-based contract, but the
methodology is point-in-time safe when callers provide a formation window:

* Engle-Granger uses the cointegration-specific MacKinnon distribution.
* Both legs must be I(1) before a relation can be marked cointegrated.
* Half-life uses the exact discrete AR(1) mapping and reports uncertainty.
* Johansen validates the I(1) assumption and rejects full-rank results.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen

logger = logging.getLogger(__name__)

HALF_LIFE_MIN = 5
HALF_LIFE_MAX = 30
EG_PVALUE_THRESHOLD = 0.05


def _positive_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return values.where(values > 0)


def _prepare_log_pair(p1: pd.Series, p2: pd.Series) -> pd.DataFrame:
    aligned = pd.concat(
        [_positive_numeric(p1).rename(str(p1.name or "p1")),
         _positive_numeric(p2).rename(str(p2.name or "p2"))],
        axis=1,
        join="inner",
    ).dropna()
    aligned = aligned.loc[~aligned.index.duplicated(keep="last")].sort_index()
    if len(aligned) < 60:
        raise ValueError(f"EG: cần ≥60 obs dương hữu hạn, có {len(aligned)}")
    return np.log(aligned)


def integration_order_check(log_prices: pd.Series, alpha: float = 0.05) -> dict:
    """Check that a log-price is non-stationary in level and stationary in delta."""
    values = pd.to_numeric(log_prices, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 60:
        return {"is_i1": False, "level_p_value": None, "diff_p_value": None}
    try:
        level_p = float(adfuller(values.values, regression="c", autolag="AIC")[1])
        diff_p = float(adfuller(values.diff().dropna().values, regression="c", autolag="AIC")[1])
    except Exception as exc:
        logger.warning("I(1) validation failed for %s: %s", values.name, exc)
        return {"is_i1": False, "level_p_value": None, "diff_p_value": None}
    return {
        "is_i1": bool(level_p >= alpha and diff_p < alpha),
        "level_p_value": level_p,
        "diff_p_value": diff_p,
    }


def engle_granger(
    p1: pd.Series,
    p2: pd.Series,
    *,
    alpha: float = EG_PVALUE_THRESHOLD,
    validate_i1: bool = True,
    trend: str = "c",
) -> dict:
    """Augmented Engle-Granger with the correct residual-test distribution.

    Orientation is explicit: ``log(p1) = alpha + beta * log(p2) + resid``.
    Callers choose it before testing; this function never tries both directions.
    """
    aligned = _prepare_log_pair(p1, p2)
    y = aligned.iloc[:, 0].to_numpy(dtype=float)
    x = aligned.iloc[:, 1].to_numpy(dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    intercept, beta = coefs
    resid_arr = y - (intercept + beta * x)
    resid = pd.Series(resid_arr, index=aligned.index, name="resid")

    try:
        coint_stat, p_value, critical_values = coint(
            y, x, trend=trend, method="aeg", autolag="aic"
        )
        coint_stat = float(coint_stat)
        p_value = float(p_value)
        critical_values = np.asarray(critical_values, dtype=float)
    except Exception as exc:
        logger.warning("Engle-Granger failed for %s/%s: %s", p1.name, p2.name, exc)
        coint_stat, p_value = float("nan"), 1.0
        critical_values = np.full(3, np.nan)

    p1_i1 = integration_order_check(aligned.iloc[:, 0], alpha=alpha)
    p2_i1 = integration_order_check(aligned.iloc[:, 1], alpha=alpha)
    i1_valid = bool(p1_i1["is_i1"] and p2_i1["is_i1"])
    is_cointegrated = bool(np.isfinite(p_value) and p_value < alpha and (i1_valid or not validate_i1))
    return {
        "beta": float(beta),
        "alpha": float(intercept),
        "orientation": f"{p1.name}/{p2.name}",
        "coint_stat": coint_stat,
        "adf_stat": coint_stat,
        "p_value": p_value,
        "q_value": p_value,
        "critical_values": critical_values,
        "is_cointegrated": is_cointegrated,
        "i1_valid": i1_valid,
        "p1_i1": p1_i1,
        "p2_i1": p2_i1,
        "resid": resid,
        "n_obs": int(len(aligned)),
        "methodology_version": "engle_granger_mackinnon_i1_v2",
    }


def adjust_pvalues_fdr(p_values: list[float] | np.ndarray, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg decisions and q-values, preserving invalid entries."""
    values = np.asarray(p_values, dtype=float)
    rejected = np.zeros(len(values), dtype=bool)
    q_values = np.full(len(values), np.nan, dtype=float)
    valid = np.isfinite(values)
    if valid.any():
        reject_valid, q_valid, _, _ = multipletests(values[valid], alpha=alpha, method="fdr_bh")
        rejected[valid] = reject_valid
        q_values[valid] = q_valid
    return rejected, q_values


def _select_johansen_lag(log_prices: pd.DataFrame) -> int:
    maxlags = max(1, min(5, len(log_prices) // 20))
    try:
        selected = VAR(log_prices).select_order(maxlags=maxlags).selected_orders.get("bic")
        var_lag = int(selected) if selected is not None else 2
    except Exception as exc:
        logger.info("Johansen lag selection fallback to VAR(2): %s", exc)
        var_lag = 2
    # coint_johansen expects the number of lagged differences (VAR lag - 1),
    # so a selected VAR(1) legitimately maps to k_ar_diff=0.
    return max(0, var_lag - 1)


def johansen_test(
    prices: pd.DataFrame,
    det_order: int = 0,
    k_ar_diff: int | None = None,
    *,
    validate_i1: bool = True,
) -> dict:
    """Johansen trace test with lag selection and I(1)/full-rank guardrails."""
    numeric = prices.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric = numeric.where(numeric > 0).dropna(how="any").sort_index()
    log_prices = np.log(numeric)
    if len(log_prices) < 100:
        raise ValueError(f"Johansen: cần ≥100 obs sau validation, có {len(log_prices)}")
    if log_prices.shape[1] < 2:
        raise ValueError("Johansen: cần ≥2 ticker")

    integration = {column: integration_order_check(log_prices[column]) for column in log_prices}
    i1_valid = all(item["is_i1"] for item in integration.values())
    selected_lag = _select_johansen_lag(log_prices) if k_ar_diff is None else int(k_ar_diff)
    if selected_lag < 0:
        raise ValueError("Johansen k_ar_diff phải >= 0")
    try:
        result = coint_johansen(log_prices.to_numpy(), det_order, selected_lag)
    except Exception as exc:
        raise RuntimeError(f"Johansen fit fail: {exc}") from exc

    trace_stat = np.asarray(result.lr1, dtype=float)
    trace_crit_95 = np.asarray(result.cvt[:, 1], dtype=float)
    raw_rank = 0
    for i, (stat, critical) in enumerate(zip(trace_stat, trace_crit_95)):
        if stat > critical:
            raw_rank = i + 1
        else:
            break
    full_rank = raw_rank >= log_prices.shape[1]
    valid = bool((i1_valid or not validate_i1) and not full_rank)
    effective_rank = raw_rank if valid else 0
    warnings: list[str] = []
    if validate_i1 and not i1_valid:
        warnings.append("Johansen assumption failed: not every log-price is I(1).")
    if full_rank:
        warnings.append("Johansen returned full rank; this is not an I(1) cointegration system.")
    return {
        "trace_stat": trace_stat,
        "trace_crit_95": trace_crit_95,
        "n_coint_vectors": int(effective_rank),
        "raw_rank": int(raw_rank),
        "eig_vectors": np.asarray(result.evec, dtype=float),
        "tickers": list(log_prices.columns),
        "k_ar_diff": selected_lag,
        "i1_valid": i1_valid,
        "integration_checks": integration,
        "valid_system": valid,
        "warnings": warnings,
    }


def ou_half_life(spread: pd.Series) -> float:
    half_life = ou_half_life_raw(spread)
    if not np.isfinite(half_life) or not (HALF_LIFE_MIN <= half_life <= HALF_LIFE_MAX):
        return float("nan")
    return half_life


def ou_half_life_diagnostics(spread: pd.Series) -> dict:
    """Exact AR(1) half-life and an approximate 95% confidence interval."""
    values = pd.to_numeric(spread, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 60:
        return {"half_life": float("nan"), "phi": float("nan"), "ci_low": None, "ci_high": None}
    aligned = pd.concat(
        [values.rename("current"), values.shift(1).rename("lagged")], axis=1
    ).dropna()
    y = aligned["current"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(aligned)), aligned["lagged"].to_numpy(dtype=float)])
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    phi = float(coefs[1])
    if not 0.0 < phi < 1.0:
        return {"half_life": float("nan"), "phi": phi, "ci_low": None, "ci_high": None}
    half_life = float(-np.log(2.0) / np.log(phi))
    residuals = y - X @ coefs
    dof = max(1, len(y) - X.shape[1])
    sigma2 = float(residuals @ residuals / dof)
    try:
        covariance = sigma2 * np.linalg.inv(X.T @ X)
        phi_se = float(np.sqrt(max(covariance[1, 1], 0.0)))
    except np.linalg.LinAlgError:
        phi_se = float("nan")
    ci_low = ci_high = None
    if np.isfinite(phi_se):
        lo_phi = max(1e-6, phi - 1.96 * phi_se)
        hi_phi = min(1 - 1e-6, phi + 1.96 * phi_se)
        ci_low = float(-np.log(2.0) / np.log(lo_phi))
        ci_high = float(-np.log(2.0) / np.log(hi_phi))
    return {"half_life": half_life, "phi": phi, "ci_low": ci_low, "ci_high": ci_high}


def ou_half_life_raw(spread: pd.Series) -> float:
    return float(ou_half_life_diagnostics(spread)["half_life"])


def hurst(spread: pd.Series, max_lag: int = 20) -> float:
    values = pd.to_numeric(spread, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    if len(values) < max_lag + 10:
        return float("nan")
    lags = np.arange(2, max_lag + 1)
    tau = np.asarray([np.std(values[lag:] - values[:-lag]) for lag in lags])
    if not np.isfinite(tau).all() or (tau <= 0).any():
        return float("nan")
    slope, _ = np.polyfit(np.log(lags), np.log(tau), 1)
    return float(slope)


def rolling_hedge_ratio(p1: pd.Series, p2: pd.Series, window: int = 126) -> pd.Series:
    """Lagged rolling OLS beta; each value uses information through t-1."""
    log_pair = _prepare_log_pair(p1, p2)
    covariance = log_pair.iloc[:, 0].shift(1).rolling(window).cov(log_pair.iloc[:, 1].shift(1))
    variance = log_pair.iloc[:, 1].shift(1).rolling(window).var()
    return (covariance / variance.replace(0, np.nan)).rename("rolling_beta")


def kalman_hedge_ratio(
    p1: pd.Series,
    p2: pd.Series,
    *,
    process_variance: float = 1e-5,
    observation_variance: float = 1e-3,
) -> pd.Series:
    """Causal two-state Kalman estimate of intercept and hedge ratio."""
    log_pair = _prepare_log_pair(p1, p2)
    state = np.array([0.0, 1.0], dtype=float)
    covariance = np.eye(2)
    process = np.eye(2) * float(process_variance)
    betas = np.full(len(log_pair), np.nan)
    for i, (y_value, x_value) in enumerate(log_pair.to_numpy(dtype=float)):
        design = np.array([1.0, x_value])
        predicted_covariance = covariance + process
        innovation_variance = float(design @ predicted_covariance @ design + observation_variance)
        gain = predicted_covariance @ design / innovation_variance
        state = state + gain * (y_value - float(design @ state))
        covariance = predicted_covariance - np.outer(gain, design) @ predicted_covariance
        betas[i] = state[1]
    return pd.Series(betas, index=log_pair.index, name="kalman_beta").shift(1)


def beta_stability(prices: pd.DataFrame, t1: str, t2: str, window: int = 126) -> dict:
    beta_series = rolling_hedge_ratio(prices[t1], prices[t2], window=window).dropna()
    if len(beta_series) < 20:
        return {"score": 0.0, "drift": None, "coefficient_of_variation": None, "stable": False}
    recent = beta_series.tail(min(60, len(beta_series)))
    mean_abs = abs(float(recent.mean()))
    cv = float(recent.std() / mean_abs) if mean_abs > 1e-12 else float("inf")
    drift = float(abs(recent.iloc[-1] / recent.iloc[0] - 1.0)) if abs(recent.iloc[0]) > 1e-12 else float("inf")
    score = float(np.clip(1.0 - max(cv, drift), 0.0, 1.0))
    return {"score": score, "drift": drift, "coefficient_of_variation": cv, "stable": bool(cv <= 0.25 and drift <= 0.25)}


def pairwise_eg_details(prices: pd.DataFrame, tickers: Optional[list[str]] = None) -> pd.DataFrame:
    """One explicitly oriented test per unordered pair plus BH q-values."""
    names = list(tickers or prices.columns)
    rows: list[dict] = []
    for i, t1 in enumerate(names):
        for t2 in names[i + 1:]:
            try:
                result = engle_granger(prices[t1], prices[t2])
                rows.append({"t1": t1, "t2": t2, **result})
            except Exception as exc:
                logger.warning("EG fail %s/%s: %s", t1, t2, exc)
    if not rows:
        return pd.DataFrame()
    details = pd.DataFrame(rows)
    rejected, q_values = adjust_pvalues_fdr(details["p_value"].to_numpy())
    details["q_value"] = q_values
    details["fdr_cointegrated"] = rejected & details["i1_valid"].to_numpy(dtype=bool)
    return details


def pairwise_eg_matrix(prices: pd.DataFrame, tickers: Optional[list[str]] = None) -> pd.DataFrame:
    """Symmetric matrix of FDR-adjusted q-values (diagonal zero)."""
    names = list(tickers or prices.columns)
    matrix = pd.DataFrame(np.nan, index=names, columns=names)
    np.fill_diagonal(matrix.values, 0.0)
    details = pairwise_eg_details(prices, names)
    for row in details.itertuples():
        matrix.loc[row.t1, row.t2] = row.q_value
        matrix.loc[row.t2, row.t1] = row.q_value
    return matrix
