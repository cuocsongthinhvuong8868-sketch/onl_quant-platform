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
Z_95 = norm.ppf(0.05)          # ≈ -1.64485 for 95% confidence (left tail)
HIST_WINDOW = 756               # ~3 years trading days
STDDEV_WINDOW = 30


def calculate_var_cvar_metrics(
    vnindex_series: pd.Series,
    include_evt: bool = True,
    evt_refit_every: int = DEFAULT_REFIT_EVERY,
    evt_threshold_pct: float = DEFAULT_THRESHOLD_PCT,
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
    df = pd.DataFrame({"price": vnindex_series.sort_index()})
    df["return"] = np.log(df["price"] / df["price"].shift(1))

    # Rolling stdev (30 ngày)
    df["stdev_30"] = df["return"].rolling(window=STDDEV_WINDOW, min_periods=STDDEV_WINDOW).std()

    # Rolling mean (30 ngày) cho Parametric VaR
    df["mean_30"] = df["return"].rolling(window=STDDEV_WINDOW, min_periods=STDDEV_WINDOW).mean()

    # Parametric VaR 95% = μ₃₀ + z₀.₀₅ × σ₃₀
    df["parametric_var"] = df["mean_30"] + Z_95 * df["stdev_30"]

    # Historical VaR 95% = rolling 5th percentile (3-year window)
    df["historical_var"] = (
        df["return"]
        .rolling(window=HIST_WINDOW, min_periods=HIST_WINDOW)
        .quantile(0.05)
    )

    # Expected Shortfall 95% = mean of returns in the 5% tail
    df["expected_shortfall"] = _rolling_expected_shortfall(
        df["return"], df["historical_var"], window=HIST_WINDOW,
    )

    classic_cols = [
        "price", "return", "mean_30", "stdev_30",
        "parametric_var", "historical_var", "expected_shortfall",
    ]

    if not include_evt:
        return df[classic_cols]

    # ── EVT-POT-GPD: extrapolate tail risk sang quantile cực đoan ──
    # Tách module evt.py vì math độc lập + nặng (scipy MLE), tránh phình metrics.py
    returns_clean = df["return"].dropna()
    df_evt = rolling_evt_metrics(
        returns_clean,
        window=HIST_WINDOW,
        refit_every=evt_refit_every,
        threshold_pct=evt_threshold_pct,
    )
    # Align EVT về full index (NaN cho phần warmup)
    df = df.join(df_evt, how="left")

    return df[classic_cols + list(df_evt.columns)]


@njit(fastmath=True, cache=True)
def _rolling_es_kernel(returns: np.ndarray, var_arr: np.ndarray, window: int) -> np.ndarray:
    """Numba kernel — O(N·W) loop nhưng compile sang native, nhanh ~50-200× pure-Python.

    ES_i = mean({ r_j | r_j ≤ VaR_i, j ∈ [i-window+1, i] })
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
