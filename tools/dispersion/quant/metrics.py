import gc
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf


def calculate_dispersion_metrics(df_prices: pd.DataFrame, index_series: pd.Series, zscore_type: str, zscore_window: int, dpi_window: int):
    stock_returns = df_prices.pct_change().dropna(how="all")
    market_returns = index_series.pct_change().reindex(stock_returns.index)

    deviations = stock_returns.sub(market_returns, axis=0)
    n_eff = stock_returns.notna().sum(axis=1)

    csad = deviations.abs().mean(axis=1, skipna=True)
    cssd = np.sqrt((deviations ** 2).sum(axis=1, skipna=True) / (n_eff - 1).clip(lower=1))
    spread = cssd - csad

    min_p = max(2, zscore_window // 2)
    if zscore_type == 'EWMA':
        spread_mean = spread.ewm(span=zscore_window, min_periods=min_p).mean()
        spread_std = spread.ewm(span=zscore_window, min_periods=min_p).std()
    else:
        spread_mean = spread.rolling(window=zscore_window, min_periods=min_p).mean()
        spread_std = spread.rolling(window=zscore_window, min_periods=min_p).std()
        
    spread_z = (spread - spread_mean) / spread_std.replace(0, np.nan)

    is_elevated = (spread_z > 0).astype(int)
    dpi_min_p = max(1, dpi_window // 2)
    dpi = is_elevated.rolling(window=dpi_window, min_periods=dpi_min_p).mean() * 100.0

    out = pd.DataFrame(
        {
            "Market_Return": market_returns,
            "CSAD": csad,
            "CSSD": cssd,
            "Spread": spread,
            "Spread_Z": spread_z,
            "DPI": dpi,
        }
    )
    return stock_returns, out


def fit_rolling_correlation(stock_returns: pd.DataFrame, window: int = 30, refit_every: int = 1, active_nan_threshold: float = 0.2):
    R = stock_returns.values
    T, _ = R.shape
    dates = stock_returns.index
    corr_arr = np.full(T, np.nan)

    cov_cache = None
    last_fit_idx = -refit_every

    for i in range(window, T):
        if i % 100 == 0:
            gc.collect()

        if (i - last_fit_idx) >= refit_every:
            window_data = R[i - window:i, :].copy()
            active_mask = np.isnan(window_data).sum(axis=0) < (window * active_nan_threshold)
            if active_mask.sum() < 5:
                continue

            X = window_data[:, active_mask]
            X = np.nan_to_num(X, nan=0.0)

            try:
                lw = LedoitWolf().fit(X)
                cov_cache = lw.covariance_
                last_fit_idx = i
            except Exception:
                continue
            finally:
                del window_data, X

        if cov_cache is None:
            continue

        std = np.sqrt(np.diag(cov_cache))
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = cov_cache / np.outer(std, std)

        n = corr.shape[0]
        corr_arr[i] = (corr.sum() - n) / (n * (n - 1))

    gc.collect()
    return pd.Series(corr_arr, index=dates, name="Ledoit_Correlation")

