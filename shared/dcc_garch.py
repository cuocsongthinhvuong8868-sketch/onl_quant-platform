"""
shared/dcc_garch.py — Dynamic Conditional Correlation (Engle 2002)

Output time-varying NxN correlation matrix R_t cho universe asset:
  Stage 1: GARCH(1,1) per asset → standardized residuals ε_it = r_it / σ_it
           (3-tier fallback giống tools/fear_greed/quant/volatility.py:32-84)
  Stage 2: DCC(1,1) MLE trên std_resid
           Q_t = (1-α-β)·Q̄ + α·ε_{t-1}ε_{t-1}' + β·Q_{t-1}
           R_t = diag(Q_t)^{-1/2} · Q_t · diag(Q_t)^{-1/2}

Hybrid tier: full DCC fit trên top-N liquid; EWMA λ=0.94 fallback cho rest.

Public API:
    fit_dcc(returns, alpha_init, beta_init) -> dict
    dynamic_correlation_matrix(returns, method, top_n_dcc) -> pd.DataFrame
    pair_correlation(returns, t1, t2, method) -> pd.Series

Caller phải pre-compute log-returns. NaN handling: drop ticker >5% NaN trong window.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Literal

import numpy as np
import pandas as pd
from arch import arch_model
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

EWMA_LAMBDA = 0.94
DCC_CACHE_NAMESPACE = "dcc_garch"
DCC_METHOD_VERSION = "v1"

# Composite likelihood threshold — N>30 quá đắt cho full MLE
COMPOSITE_LIKELIHOOD_N_THRESHOLD = 30


# ────────────────────────────────────────────────────────────────────
# Univariate GARCH stage
# ────────────────────────────────────────────────────────────────────


def _ewma_variance(y: np.ndarray, lambda_: float = EWMA_LAMBDA) -> np.ndarray:
    """RiskMetrics EWMA variance — luôn produce non-NaN (ngoại trừ warmup)."""
    n = len(y)
    var = np.full(n, np.nan)
    seed = np.nanvar(y[: min(30, n)])
    if not np.isfinite(seed) or seed <= 0:
        seed = 1.0
    var[0] = seed
    for t in range(1, n):
        prev = var[t - 1] if np.isfinite(var[t - 1]) else seed
        r2 = y[t - 1] ** 2 if np.isfinite(y[t - 1]) else 0.0
        var[t] = lambda_ * prev + (1.0 - lambda_) * r2
    return var


def _fit_univariate_for_dcc(series: pd.Series, ticker: str) -> dict:
    """Fit univariate GARCH cho 1 asset; return raw conditional_vol + std_resid.

    Khác với tools/fear_greed/quant/volatility.py:fit_egarch() vì DCC cần
    raw cond_vol (KHÔNG annualize) để compute standardized residuals đúng scale.
    """
    s = series.dropna()
    if len(s) < 100:
        raise ValueError(f"{ticker}: cần ≥100 obs, có {len(s)}")

    y = np.ascontiguousarray(s.values * 100, dtype=np.float64)  # arch lib convention %

    # Tier 1: GARCH(1,1) Normal — đủ cho DCC step 1, không cần leverage/skew
    try:
        res = arch_model(y, vol="GARCH", p=1, q=1, dist="normal").fit(
            update_freq=0, disp="off"
        )
        if getattr(res, "convergence_flag", 0) == 0:
            cond_vol = np.asarray(res.conditional_volatility)
            std_resid = (y - res.params.get("mu", 0.0)) / cond_vol
            return {
                "std_resid": pd.Series(std_resid, index=s.index, name=ticker),
                "cond_vol": pd.Series(cond_vol, index=s.index, name=ticker),
                "method": "GARCH",
            }
        logger.warning("%s: GARCH(1,1) convergence_flag != 0 — fallback EWMA", ticker)
    except Exception as exc:
        logger.warning("%s: GARCH(1,1) fail: %s — fallback EWMA", ticker, exc)

    # Tier 2: EWMA fallback
    var = _ewma_variance(y, EWMA_LAMBDA)
    cond_vol = np.sqrt(var)
    std_resid = y / cond_vol
    return {
        "std_resid": pd.Series(std_resid, index=s.index, name=ticker),
        "cond_vol": pd.Series(cond_vol, index=s.index, name=ticker),
        "method": "EWMA",
    }


# ────────────────────────────────────────────────────────────────────
# DCC MLE stage
# ────────────────────────────────────────────────────────────────────


def _dcc_q_recursion(eps: np.ndarray, alpha: float, beta: float, Q_bar: np.ndarray) -> np.ndarray:
    """Compute Q_t trajectory. eps: T×N std residuals. Q_bar: N×N unconditional cov."""
    T, N = eps.shape
    Q = np.zeros((T, N, N))
    Q[0] = Q_bar.copy()
    one_minus = 1.0 - alpha - beta
    for t in range(1, T):
        Q[t] = one_minus * Q_bar + alpha * np.outer(eps[t - 1], eps[t - 1]) + beta * Q[t - 1]
    return Q


def _dcc_log_likelihood(params: np.ndarray, eps: np.ndarray, Q_bar: np.ndarray) -> float:
    """DCC negative log-likelihood (full multivariate Gaussian).

    Skip Gaussian constant + univariate part (those depend only on uni-GARCH).
    """
    alpha, beta = params
    if alpha < 1e-6 or beta < 1e-6 or alpha + beta > 0.9999:
        return 1e10
    T, N = eps.shape
    try:
        Q_traj = _dcc_q_recursion(eps, alpha, beta, Q_bar)
        nll = 0.0
        for t in range(T):
            Q_t = Q_traj[t]
            d_inv = 1.0 / np.sqrt(np.diag(Q_t))
            R_t = Q_t * np.outer(d_inv, d_inv)
            # Symmetric & PD safeguard
            R_t = 0.5 * (R_t + R_t.T)
            sign, log_det = np.linalg.slogdet(R_t)
            if sign <= 0 or not np.isfinite(log_det):
                return 1e10
            try:
                inv_R = np.linalg.inv(R_t)
            except np.linalg.LinAlgError:
                return 1e10
            nll += 0.5 * (log_det + eps[t] @ inv_R @ eps[t] - eps[t] @ eps[t])
        return nll
    except Exception as exc:
        logger.debug("DCC LL fail params=%s: %s", params, exc)
        return 1e10


def _dcc_composite_likelihood(params: np.ndarray, eps: np.ndarray, Q_bar: np.ndarray) -> float:
    """Engle-Sheppard composite likelihood: sum bivariate NLLs over all pairs.

    Cheap khi N>30. Mỗi pair là 2×2 → analytical inverse, no slogdet.
    """
    alpha, beta = params
    if alpha < 1e-6 or beta < 1e-6 or alpha + beta > 0.9999:
        return 1e10
    T, N = eps.shape
    nll = 0.0
    one_minus = 1.0 - alpha - beta
    for i in range(N):
        for j in range(i + 1, N):
            q_bar_ii = Q_bar[i, i]
            q_bar_jj = Q_bar[j, j]
            q_bar_ij = Q_bar[i, j]
            q_ii, q_jj, q_ij = q_bar_ii, q_bar_jj, q_bar_ij
            for t in range(1, T):
                e_i_prev = eps[t - 1, i]
                e_j_prev = eps[t - 1, j]
                q_ii = one_minus * q_bar_ii + alpha * e_i_prev**2 + beta * q_ii
                q_jj = one_minus * q_bar_jj + alpha * e_j_prev**2 + beta * q_jj
                q_ij = one_minus * q_bar_ij + alpha * e_i_prev * e_j_prev + beta * q_ij
                rho = q_ij / np.sqrt(q_ii * q_jj)
                if abs(rho) >= 0.99999:
                    return 1e10
                one_m_r2 = 1.0 - rho * rho
                e_i = eps[t, i]
                e_j = eps[t, j]
                nll += 0.5 * (
                    np.log(one_m_r2)
                    + (e_i**2 + e_j**2 - 2 * rho * e_i * e_j) / one_m_r2
                    - (e_i**2 + e_j**2)
                )
    return nll


def fit_dcc(
    returns: pd.DataFrame,
    alpha_init: float = 0.05,
    beta_init: float = 0.92,
) -> dict:
    """Fit DCC(1,1) trên N-asset returns.

    Parameters
    ----------
    returns : pd.DataFrame
        index = date, columns = tickers. Đã pre-compute log-returns hoặc % returns.
        NaN sẽ bị drop per-ticker; tickers với <100 obs sẽ raise.

    Returns
    -------
    dict với keys:
      Q_bar       : (N,N) unconditional Q matrix
      alpha, beta : DCC params
      std_resid   : pd.DataFrame T×N standardized residuals
      uni_garch   : dict[ticker] -> {"method": str, "cond_vol": Series}
      tickers     : list[str]
      converged   : bool
      ll_method   : "full" | "composite"
    """
    if returns.empty or returns.shape[1] < 2:
        raise ValueError("Cần ≥2 ticker để fit DCC")

    # 1) Univariate GARCH per ticker
    uni_results = {}
    std_resid_dict = {}
    cond_vol_dict = {}
    for ticker in returns.columns:
        try:
            uni = _fit_univariate_for_dcc(returns[ticker], ticker)
            uni_results[ticker] = {"method": uni["method"], "cond_vol": uni["cond_vol"]}
            std_resid_dict[ticker] = uni["std_resid"]
            cond_vol_dict[ticker] = uni["cond_vol"]
        except Exception as exc:
            logger.warning("Skip %s từ DCC: %s", ticker, exc)

    if len(std_resid_dict) < 2:
        raise RuntimeError("Sau univariate stage <2 ticker còn lại, không fit DCC được")

    eps_df = pd.DataFrame(std_resid_dict).dropna(how="any")
    if len(eps_df) < 100:
        raise RuntimeError(f"Sau align std_resid còn {len(eps_df)} obs <100")

    tickers = list(eps_df.columns)
    eps = eps_df.values  # T×N
    N = len(tickers)
    Q_bar = np.cov(eps, rowvar=False)

    # 2) DCC MLE
    use_composite = N > COMPOSITE_LIKELIHOOD_N_THRESHOLD
    obj_fn = _dcc_composite_likelihood if use_composite else _dcc_log_likelihood
    logger.info(
        "DCC MLE: N=%d, T=%d, method=%s",
        N, len(eps), "composite" if use_composite else "full",
    )

    result = minimize(
        obj_fn,
        x0=[alpha_init, beta_init],
        args=(eps, Q_bar),
        method="L-BFGS-B",
        bounds=[(1e-4, 0.3), (0.5, 0.999)],
        options={"maxiter": 50, "ftol": 1e-6},
    )
    alpha, beta = result.x
    converged = bool(result.success) and (alpha + beta < 0.9995)

    if not converged:
        logger.warning(
            "DCC không hội tụ — fallback EWMA cho dynamic correlation (alpha=%.4f, beta=%.4f, success=%s)",
            alpha, beta, result.success,
        )

    return {
        "Q_bar": Q_bar,
        "alpha": float(alpha),
        "beta": float(beta),
        "std_resid": eps_df,
        "uni_garch": uni_results,
        "tickers": tickers,
        "converged": converged,
        "ll_method": "composite" if use_composite else "full",
    }


# ────────────────────────────────────────────────────────────────────
# EWMA fallback (RiskMetrics)
# ────────────────────────────────────────────────────────────────────


def _ewma_correlation(returns: pd.DataFrame, lambda_: float = EWMA_LAMBDA) -> pd.DataFrame:
    """RiskMetrics EWMA correlation — return last-date NxN matrix.

    Robust fallback khi DCC fail hoặc dùng cho ticker ngoài top-N liquid.
    NaN ticker được drop.
    """
    df = returns.dropna(how="any")
    if df.empty:
        raise ValueError("EWMA correlation: returns rỗng sau dropna")
    x = df.values
    T, N = x.shape

    # EWMA covariance recursion
    cov = np.cov(x[: min(30, T)], rowvar=False)
    for t in range(1, T):
        cov = lambda_ * cov + (1.0 - lambda_) * np.outer(x[t - 1], x[t - 1])

    d = np.sqrt(np.diag(cov))
    corr = cov / np.outer(d, d)
    corr = np.clip(corr, -1.0, 1.0)
    return pd.DataFrame(corr, index=df.columns, columns=df.columns)


def _ewma_pair_correlation_series(returns: pd.DataFrame, t1: str, t2: str, lambda_: float = EWMA_LAMBDA) -> pd.Series:
    """EWMA time-series rho_t cho 1 pair."""
    sub = returns[[t1, t2]].dropna()
    if len(sub) < 30:
        raise ValueError(f"EWMA pair {t1}/{t2}: <30 obs")
    x = sub.values
    T = len(x)
    # Seed với 30-obs sample cov
    cov_00, cov_11, cov_01 = np.cov(x[:30], rowvar=False).flatten()[[0, 3, 1]]
    rho = np.full(T, np.nan)
    rho[0] = cov_01 / np.sqrt(cov_00 * cov_11)
    for t in range(1, T):
        r0 = x[t - 1, 0]
        r1 = x[t - 1, 1]
        cov_00 = lambda_ * cov_00 + (1 - lambda_) * r0 * r0
        cov_11 = lambda_ * cov_11 + (1 - lambda_) * r1 * r1
        cov_01 = lambda_ * cov_01 + (1 - lambda_) * r0 * r1
        denom = np.sqrt(cov_00 * cov_11)
        rho[t] = cov_01 / denom if denom > 1e-12 else np.nan
    return pd.Series(np.clip(rho, -1.0, 1.0), index=sub.index, name=f"rho_{t1}_{t2}")


# ────────────────────────────────────────────────────────────────────
# Liquid universe selection
# ────────────────────────────────────────────────────────────────────


def _select_liquid_universe(returns: pd.DataFrame, top_n: int = 50, nan_threshold: float = 0.05) -> list[str]:
    """Chọn top-N ticker theo trailing 60d mean dollar-volume.

    Dollar volume cần load thông qua shared.data_loader.load_volumes() + close prices.
    Nếu load_volumes() trả None → fallback ranking by inverse-NaN ratio.
    """
    from shared.data_loader import load_close_prices, load_volumes

    # Filter ticker với <nan_threshold NaN trong returns window
    nan_ratio = returns.isna().mean()
    eligible = nan_ratio[nan_ratio < nan_threshold].index.tolist()
    if len(eligible) <= top_n:
        logger.info("Eligible tickers (NaN<%.0f%%) = %d ≤ top_n, dùng hết", nan_threshold * 100, len(eligible))
        return eligible

    volumes = load_volumes()
    if volumes is None:
        logger.warning("load_volumes() None — fallback rank by inverse-NaN ratio")
        return nan_ratio.loc[eligible].nsmallest(top_n).index.tolist()

    close = load_close_prices()
    # Trailing 60d window
    end_date = returns.index[-1]
    start_date = end_date - pd.Timedelta(days=90)  # 90 calendar ≈ 60 trading
    dv = (
        close.loc[start_date:end_date, eligible]
        * volumes.loc[start_date:end_date, eligible].reindex(columns=eligible)
    ).mean(axis=0)
    top = dv.sort_values(ascending=False).head(top_n).index.tolist()
    logger.info("Liquid universe top-%d: %s ... %s", top_n, top[:3], top[-3:])
    return top


# ────────────────────────────────────────────────────────────────────
# Public high-level API
# ────────────────────────────────────────────────────────────────────


def dynamic_correlation_matrix(
    returns: pd.DataFrame,
    method: Literal["dcc", "ewma", "hybrid"] = "hybrid",
    top_n_dcc: int = 50,
) -> pd.DataFrame:
    """NxN last-date dynamic correlation matrix.

    method:
      "dcc"    : full DCC fit trên all ticker. Cẩn thận khi N>50 (chậm + unstable).
      "ewma"   : RiskMetrics EWMA λ=0.94 (cheap, no fitting).
      "hybrid" : DCC fit top-N liquid; EWMA cho phần còn lại + cross blocks.
    """
    if method == "ewma":
        return _ewma_correlation(returns)

    if method == "dcc":
        fit = fit_dcc(returns)
        if not fit["converged"]:
            logger.warning("DCC fail, downgrade EWMA cho dynamic_correlation_matrix")
            return _ewma_correlation(returns)
        return _dcc_last_correlation(fit)

    # hybrid
    liquid = _select_liquid_universe(returns, top_n_dcc)
    all_tickers = list(returns.columns)
    tail = [t for t in all_tickers if t not in liquid]

    # DCC block on liquid
    dcc_block = pd.DataFrame(
        np.eye(len(liquid)), index=liquid, columns=liquid
    )
    try:
        fit = fit_dcc(returns[liquid])
        if fit["converged"]:
            dcc_block = _dcc_last_correlation(fit)
        else:
            logger.warning("DCC hybrid block fail, dùng EWMA cho liquid block")
            dcc_block = _ewma_correlation(returns[liquid])
    except Exception as exc:
        logger.warning("DCC hybrid block exception: %s — EWMA fallback", exc)
        dcc_block = _ewma_correlation(returns[liquid])

    # EWMA tail block + cross block
    if tail:
        ewma_full = _ewma_correlation(returns[liquid + tail])
        # Stitch: liquid×liquid = dcc, mọi cell khác = ewma
        result = ewma_full.copy()
        for r in dcc_block.index:
            for c in dcc_block.columns:
                result.loc[r, c] = dcc_block.loc[r, c]
        return result.loc[all_tickers, all_tickers]
    return dcc_block.loc[liquid, liquid]


def _dcc_last_correlation(fit_result: dict) -> pd.DataFrame:
    """Reconstruct Q_T → R_T từ fit_dcc output."""
    eps = fit_result["std_resid"].values
    alpha = fit_result["alpha"]
    beta = fit_result["beta"]
    Q_bar = fit_result["Q_bar"]
    Q_traj = _dcc_q_recursion(eps, alpha, beta, Q_bar)
    Q_T = Q_traj[-1]
    d_inv = 1.0 / np.sqrt(np.diag(Q_T))
    R_T = Q_T * np.outer(d_inv, d_inv)
    R_T = np.clip(R_T, -1.0, 1.0)
    return pd.DataFrame(R_T, index=fit_result["tickers"], columns=fit_result["tickers"])


def pair_correlation(
    returns: pd.DataFrame,
    t1: str,
    t2: str,
    method: Literal["dcc", "ewma"] = "ewma",
) -> pd.Series:
    """Time-series rho_t cho 1 pair.

    pairs_trading sẽ consume series này như filter — entry chỉ khi
    rho_t > correlation_threshold (vd 0.5).

    method="ewma" mặc định vì cheap. "dcc" sẽ fit 2-asset DCC (full MLE).
    """
    if t1 not in returns.columns or t2 not in returns.columns:
        raise KeyError(f"Ticker {t1} hoặc {t2} không trong returns columns")

    if method == "ewma":
        return _ewma_pair_correlation_series(returns, t1, t2)

    # DCC 2-asset
    fit = fit_dcc(returns[[t1, t2]])
    if not fit["converged"]:
        logger.warning("DCC pair %s/%s fail — EWMA fallback", t1, t2)
        return _ewma_pair_correlation_series(returns, t1, t2)
    eps = fit["std_resid"].values
    alpha = fit["alpha"]
    beta = fit["beta"]
    Q_bar = fit["Q_bar"]
    Q_traj = _dcc_q_recursion(eps, alpha, beta, Q_bar)
    rho = Q_traj[:, 0, 1] / np.sqrt(Q_traj[:, 0, 0] * Q_traj[:, 1, 1])
    return pd.Series(np.clip(rho, -1.0, 1.0), index=fit["std_resid"].index, name=f"rho_{t1}_{t2}")


# ────────────────────────────────────────────────────────────────────
# Cache wrappers (reuse shared/daily_cache.py)
# ────────────────────────────────────────────────────────────────────


def _build_cache_key(tickers: list[str], top_n_dcc: int, method: str) -> dict:
    """Stable cache key bao gồm method version + ticker hash."""
    tickers_hash = hashlib.sha1(
        json.dumps(sorted(tickers), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "dcc_method": DCC_METHOD_VERSION,
        "method": method,
        "tickers_hash": tickers_hash,
        "n_tickers": len(tickers),
        "top_n_dcc": top_n_dcc,
    }


def dynamic_correlation_matrix_cached(
    returns: pd.DataFrame,
    method: Literal["dcc", "ewma", "hybrid"] = "hybrid",
    top_n_dcc: int = 50,
) -> pd.DataFrame:
    """Cached version. Cache key bao gồm tickers hash + method + last date.

    data_date dùng `returns.index[-1].isoformat()` thay vì date.today()
    để tránh timezone bug giữa Streamlit Cloud (UTC) và VN (UTC+7).
    """
    from shared.daily_cache import load_daily_cache, save_daily_cache

    tickers = list(returns.columns)
    key = _build_cache_key(tickers, top_n_dcc, method)
    data_date = returns.index[-1].isoformat()

    cached = load_daily_cache(DCC_CACHE_NAMESPACE, key, data_date=data_date)
    if cached is not None:
        logger.info("DCC cache hit cho %s", data_date)
        return cached

    logger.info("DCC cache miss — fitting (this may take 5-10 min cho top-50)")
    result = dynamic_correlation_matrix(returns, method=method, top_n_dcc=top_n_dcc)
    save_daily_cache(DCC_CACHE_NAMESPACE, key, result, data_date=data_date)
    return result
