import pandas as pd
import numpy as np
from scipy.stats import norm

# ── Constants ──
Z_95 = norm.ppf(0.05)          # ≈ -1.64485 for 95% confidence (left tail)
HIST_WINDOW = 756               # ~3 years trading days
STDDEV_WINDOW = 30


def calculate_var_cvar_metrics(vnindex_series: pd.Series) -> pd.DataFrame:
    """
    Tính rolling risk metrics cho VNINDEX:
      - log_return
      - rolling_stdev_30
      - parametric_var_95  (Gaussian VaR)
      - historical_var_95  (rolling 5th percentile, 3-year window)
      - expected_shortfall_95 (mean of tail ≤ historical_var_95)

    Parameters
    ----------
    vnindex_series : pd.Series
        Giá đóng cửa VNINDEX, index=Date, values=float.

    Returns
    -------
    pd.DataFrame
        Columns: [price, return, stdev_30, parametric_var, historical_var, expected_shortfall]
        Index: Date.
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
    # Tính bằng cách: với mỗi ngày, lấy mean của các return trong window ≤ historical_var tại ngày đó
    df["expected_shortfall"] = _rolling_expected_shortfall(df["return"], df["historical_var"], window=HIST_WINDOW)

    return df[["price", "return", "stdev_30", "parametric_var", "historical_var", "expected_shortfall"]]


def _rolling_expected_shortfall(returns: pd.Series, var_series: pd.Series, window: int = HIST_WINDOW) -> pd.Series:
    """
    Tính rolling Expected Shortfall: trung bình của các return nằm trong tail (≤ VaR).
    Với mỗi ngày i, ES_i = mean( { r_j | r_j ≤ VaR_i, j ∈ [i-window+1, i] } )
    """
    es = pd.Series(index=returns.index, dtype=float)
    for i in range(len(returns)):
        if i < window - 1:
            continue
        window_returns = returns.iloc[i - window + 1 : i + 1]
        var_threshold = var_series.iloc[i]
        if pd.isna(var_threshold):
            continue
        tail = window_returns[window_returns <= var_threshold]
        if len(tail) > 0:
            es.iloc[i] = tail.mean()
        else:
            es.iloc[i] = var_threshold
    return es
