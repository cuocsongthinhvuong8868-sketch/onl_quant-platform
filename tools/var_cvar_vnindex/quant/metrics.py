import pandas as pd
import numpy as np
from numba import njit
from scipy.stats import norm

from tools.var_cvar_vnindex.quant.evt import (
    rolling_evt_metrics,
    DEFAULT_REFIT_EVERY,
    DEFAULT_THRESHOLD_PCT,
)

# ── Constants ──
METHOD_VERSION = "var_cvar_vnindex_v3.0.0"
Z_95 = norm.ppf(0.05)          # ≈ -1.64485 for 95% confidence (left tail)
Z_99 = norm.ppf(0.01)
HIST_WINDOW = 756               # ~3 years trading days
STDDEV_WINDOW = 30
DEFAULT_MAX_ABS_SIMPLE_RETURN = 0.50


def calculate_var_cvar_metrics(
    vnindex_series: pd.Series,
    include_evt: bool = True,
    evt_refit_every: int = DEFAULT_REFIT_EVERY,
    evt_threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    hist_window: int = HIST_WINDOW,
    stddev_window: int = STDDEV_WINDOW,
    max_abs_simple_return: float = DEFAULT_MAX_ABS_SIMPLE_RETURN,
) -> pd.DataFrame:
    """
    Tính rolling risk metrics cho VNINDEX:
      Classic:
        - log_return
        - rolling_stdev_30
        - parametric_var_95   (Gaussian VaR)
        - historical_var_95   (rolling 5th percentile, 3-year window)
        - expected_shortfall_95 (mean of tail ≤ historical_var_95)
      EVT (Extreme Value Theory):
        - evt_var_95 / evt_var_99 / evt_var_995  (POT-GPD extrapolated VaR)
        - evt_es_95  / evt_es_99  / evt_es_995   (POT-GPD extrapolated ES)
        - evt_xi     (GPD shape parameter — heavy tail indicator)
        - evt_beta   (GPD scale parameter)
        - evt_threshold      (loss-scale u, positive)
        - evt_n_exceed       (số exceedances trong window)
        - hill_index         (Hill tail index — cross-check cho ξ)

    Parameters
    ----------
    vnindex_series : pd.Series
        Giá đóng cửa VNINDEX, index=Date, values=float.
    include_evt : bool
        Có tính EVT-POT-GPD không (default True). Set False để skip nếu chỉ cần
        classic metrics (vd. backtest tốc độ cao).
    evt_refit_every : int
        Số phiên giữa các lần refit GPD (default 21 ≈ 1 tháng).
    evt_threshold_pct : float
        Threshold percentile cho POT (default 0.10 = top 10% losses).

    Returns
    -------
    pd.DataFrame, index=Date.
    """
    price = pd.to_numeric(vnindex_series.sort_index(), errors="coerce")
    if price.index.has_duplicates:
        price = price.groupby(level=0).last()
    df = pd.DataFrame({"price": price})
    df["simple_return_raw"] = df["price"].pct_change(fill_method=None)
    valid_return = (
        np.isfinite(df["simple_return_raw"])
        & (df["simple_return_raw"].abs() <= max_abs_simple_return)
        & (df["simple_return_raw"] > -1.0)
    )
    df["bad_return_flag"] = df["simple_return_raw"].notna() & ~valid_return
    df["simple_return"] = df["simple_return_raw"].where(valid_return)
    df["return"] = np.log1p(df["simple_return"])
    df["return_for_risk_model"] = df["return"].shift(1)

    # Rolling stdev/mean use prior-window returns only, so same-date VaR does not learn from T return.
    model_returns = df["return_for_risk_model"]
    df["stdev_30"] = model_returns.rolling(window=stddev_window, min_periods=stddev_window).std()

    # Rolling mean for Parametric VaR
    df["mean_30"] = model_returns.rolling(window=stddev_window, min_periods=stddev_window).mean()

    # Parametric VaR = μ + z × σ, estimated from prior window.
    df["parametric_var"] = df["mean_30"] + Z_95 * df["stdev_30"]
    df["gaussian_var_99"] = df["mean_30"] + Z_99 * df["stdev_30"]

    # Historical VaR 95% = prior-window rolling 5th percentile (3-year window)
    df["historical_var"] = (
        model_returns
        .rolling(window=hist_window, min_periods=hist_window)
        .quantile(0.05)
    )

    # Expected Shortfall 95% = mean of returns in the 5% tail
    df["expected_shortfall"] = _rolling_expected_shortfall(
        model_returns, df["historical_var"], window=hist_window,
    )
    df["es_var_spread"] = df["expected_shortfall"] - df["historical_var"]
    df["var_breach_95"] = (
        df["return"].notna()
        & df["historical_var"].notna()
        & (df["return"] < df["historical_var"])
    )
    df["breach_margin_95"] = df["historical_var"] - df["return"]

    classic_cols = [
        "price", "simple_return", "return", "return_for_risk_model", "bad_return_flag",
        "mean_30", "stdev_30", "parametric_var", "gaussian_var_99",
        "historical_var", "expected_shortfall", "es_var_spread",
        "var_breach_95", "breach_margin_95",
    ]

    if not include_evt:
        return df[classic_cols]

    # ── EVT-POT-GPD: extrapolate tail risk sang quantile cực đoan ──
    # Tách module evt.py vì math độc lập + nặng (scipy MLE), tránh phình metrics.py
    returns_clean = df["return_for_risk_model"].dropna()
    df_evt = rolling_evt_metrics(
        returns_clean,
        window=hist_window,
        refit_every=evt_refit_every,
        threshold_pct=evt_threshold_pct,
    )
    # Align EVT về full index (NaN cho phần warmup)
    df = df.join(df_evt, how="left")

    if "evt_var_99" in df.columns:
        df["evt_gaussian_var99_gap"] = df["evt_var_99"] - df["gaussian_var_99"]
        return df[classic_cols + list(df_evt.columns) + ["evt_gaussian_var99_gap"]]

    return df[classic_cols + list(df_evt.columns)]


@njit(fastmath=True, cache=True)
def _rolling_es_kernel(returns: np.ndarray, var_arr: np.ndarray, window: int) -> np.ndarray:
    """Numba kernel — O(N·W) loop nhưng compile sang native, nhanh ~50-200× pure-Python.

    ES_i = mean({ r_j | r_j ≤ VaR_i, j ∈ [i-window+1, i] })
    Caller passes prior-window model returns, so ES at date T excludes T return.
    Fallback ES_i = VaR_i nếu tail rỗng (giữ semantic của bản pandas cũ).
    """
    n = returns.shape[0]
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        var_thr = var_arr[i]
        if np.isnan(var_thr):
            continue
        start = i - window + 1
        s = 0.0
        c = 0
        for j in range(start, i + 1):
            r = returns[j]
            if not np.isnan(r) and r <= var_thr:
                s += r
                c += 1
        out[i] = s / c if c > 0 else var_thr
    return out


def _rolling_expected_shortfall(returns: pd.Series, var_series: pd.Series, window: int = HIST_WINDOW) -> pd.Series:
    """
    Tính rolling Expected Shortfall: trung bình của các return nằm trong tail (≤ VaR).
    Với mỗi ngày i, ES_i = mean( { r_j | r_j ≤ VaR_i, j ∈ [i-window+1, i] } )

    Wrap quanh numba kernel để giữ API pandas-style cho caller.
    """
    arr_ret = returns.to_numpy(dtype=np.float64, copy=False)
    arr_var = var_series.reindex(returns.index).to_numpy(dtype=np.float64, copy=False)
    es_arr = _rolling_es_kernel(arr_ret, arr_var, int(window))
    return pd.Series(es_arr, index=returns.index)


def classify_tail_regime(
    evt_xi: float,
    xi_min: float | None = None,
    xi_range: float | None = None,
    var_breach_95: bool = False,
) -> str:
    evt_xi = float(evt_xi) if np.isfinite(evt_xi) else np.nan
    xi_min_val = float(xi_min) if xi_min is not None and np.isfinite(xi_min) else np.nan
    xi_range_val = float(xi_range) if xi_range is not None and np.isfinite(xi_range) else np.nan

    robust_fat = np.isfinite(evt_xi) and evt_xi >= 0.30 and np.isfinite(xi_min_val) and xi_min_val >= 0.30
    robust_heavy = np.isfinite(evt_xi) and evt_xi >= 0.15 and np.isfinite(xi_min_val) and xi_min_val >= 0.15
    threshold_sensitive_fat = (
        np.isfinite(evt_xi)
        and evt_xi >= 0.30
        and (not np.isfinite(xi_min_val) or xi_min_val < 0.30 or (np.isfinite(xi_range_val) and xi_range_val > 0.10))
    )

    if var_breach_95 and robust_fat:
        return "TAIL_STRESS_ACTIVE_ROBUST_FAT"
    if var_breach_95 and (threshold_sensitive_fat or robust_heavy):
        return "TAIL_STRESS_ACTIVE"
    if var_breach_95:
        return "VAR_BREACH_ACTIVE"
    if robust_fat:
        return "ROBUST_FAT_TAIL"
    if threshold_sensitive_fat:
        return "THRESHOLD_SENSITIVE_FAT_TAIL"
    if robust_heavy:
        return "ROBUST_HEAVY_TAIL"
    if np.isfinite(evt_xi) and evt_xi >= 0.15:
        return "HEAVY_TAIL_WATCH"
    return "NORMAL_TAIL"


def summarize_var_cvar_state(
    latest: pd.Series,
    sensitivity: pd.DataFrame | None = None,
    intervals: dict | None = None,
) -> dict:
    valid_sensitivity = pd.DataFrame()
    if sensitivity is not None and not sensitivity.empty and "status" in sensitivity.columns:
        valid_sensitivity = sensitivity[sensitivity["status"] == "ok"]

    xi_min = float(valid_sensitivity["xi"].min()) if not valid_sensitivity.empty else np.nan
    xi_max = float(valid_sensitivity["xi"].max()) if not valid_sensitivity.empty else np.nan
    xi_range = xi_max - xi_min if np.isfinite(xi_min) and np.isfinite(xi_max) else np.nan
    var99_range = (
        float(valid_sensitivity["evt_var_99"].max() - valid_sensitivity["evt_var_99"].min())
        if not valid_sensitivity.empty and "evt_var_99" in valid_sensitivity
        else np.nan
    )
    es99_range = (
        float(valid_sensitivity["evt_es_99"].max() - valid_sensitivity["evt_es_99"].min())
        if not valid_sensitivity.empty and "evt_es_99" in valid_sensitivity
        else np.nan
    )

    threshold_stable = (
        np.isfinite(xi_range)
        and xi_range <= 0.10
        and np.isfinite(var99_range)
        and abs(var99_range) <= 0.01
        and np.isfinite(es99_range)
        and abs(es99_range) <= 0.015
    )
    tail_regime = classify_tail_regime(
        float(latest.get("evt_xi", np.nan)),
        xi_min=xi_min,
        xi_range=xi_range,
        var_breach_95=bool(latest.get("var_breach_95", False)),
    )

    xi_p05 = np.nan
    xi_p95 = np.nan
    if intervals and intervals.get("status") == "ok":
        xi_interval = intervals.get("xi", {})
        xi_p05 = float(xi_interval.get("p05", np.nan))
        xi_p95 = float(xi_interval.get("p95", np.nan))

    if tail_regime.startswith("TAIL_STRESS") or tail_regime == "ROBUST_FAT_TAIL":
        tail_risk_level = "HIGH"
    elif tail_regime in {"VAR_BREACH_ACTIVE", "THRESHOLD_SENSITIVE_FAT_TAIL", "ROBUST_HEAVY_TAIL"}:
        tail_risk_level = "ELEVATED"
    elif tail_regime == "HEAVY_TAIL_WATCH":
        tail_risk_level = "WATCH"
    else:
        tail_risk_level = "LOW"

    return {
        "methodology_version": METHOD_VERSION,
        "tail_regime": tail_regime,
        "tail_risk_level": tail_risk_level,
        "var_breach_95": bool(latest.get("var_breach_95", False)),
        "breach_margin_95": float(latest.get("breach_margin_95", np.nan)),
        "current_return": float(latest.get("return", np.nan)),
        "evt_threshold_stable": bool(threshold_stable),
        "evt_sensitivity_xi_min": xi_min,
        "evt_sensitivity_xi_max": xi_max,
        "evt_sensitivity_xi_range": xi_range,
        "evt_sensitivity_var99_range": var99_range,
        "evt_sensitivity_es99_range": es99_range,
        "evt_xi_p05": xi_p05,
        "evt_xi_p95": xi_p95,
    }
