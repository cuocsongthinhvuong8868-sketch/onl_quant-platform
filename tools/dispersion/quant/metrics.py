import gc
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

METHOD_VERSION = "dispersion_v2.0.0"
DEFAULT_MAX_ABS_RETURN = 0.50


def _clean_returns(returns: pd.DataFrame, max_abs_return: float = DEFAULT_MAX_ABS_RETURN) -> pd.DataFrame:
    cleaned = returns.replace([np.inf, -np.inf], np.nan)
    if max_abs_return > 0:
        cleaned = cleaned.mask(cleaned.abs() > max_abs_return)
    return cleaned


def _zscore(series: pd.Series, zscore_type: str, zscore_window: int) -> pd.Series:
    min_p = max(2, zscore_window // 2)
    if zscore_type == "EWMA":
        mean = series.ewm(span=zscore_window, min_periods=min_p).mean()
        std = series.ewm(span=zscore_window, min_periods=min_p).std()
    else:
        mean = series.rolling(window=zscore_window, min_periods=min_p).mean()
        std = series.rolling(window=zscore_window, min_periods=min_p).std()
    return (series - mean) / std.replace(0, np.nan)


def calculate_dispersion_metrics(
    df_prices: pd.DataFrame,
    index_series: pd.Series,
    zscore_type: str = "Rolling",
    zscore_window: int = 60,
    dpi_window: int = 60,
    max_abs_return: float = DEFAULT_MAX_ABS_RETURN,
):
    stock_returns = _clean_returns(
        df_prices.pct_change(fill_method=None),
        max_abs_return=max_abs_return,
    ).dropna(how="all")
    market_returns = (
        index_series.pct_change(fill_method=None)
        .replace([np.inf, -np.inf], np.nan)
        .reindex(stock_returns.index)
    )
    stock_returns = stock_returns.loc[stock_returns.abs().sum(axis=1) > 0.001]
    market_returns = market_returns.reindex(stock_returns.index)

    deviations = stock_returns.sub(market_returns, axis=0)
    n_eff = stock_returns.notna().sum(axis=1)

    csad = deviations.abs().mean(axis=1, skipna=True)
    cssd = np.sqrt((deviations ** 2).sum(axis=1, skipna=True) / (n_eff - 1).clip(lower=1))
    cs_skewness = deviations.skew(axis=1, skipna=True)
    cs_kurtosis = deviations.kurt(axis=1, skipna=True)
    spread = cssd - csad
    spread_z = _zscore(spread, zscore_type, zscore_window)
    csad_z = _zscore(csad, zscore_type, zscore_window)
    cssd_z = _zscore(cssd, zscore_type, zscore_window)

    downside_participation = ((stock_returns < -0.02).sum(axis=1) / n_eff.replace(0, np.nan)) * 100.0
    upside_participation = ((stock_returns > 0.02).sum(axis=1) / n_eff.replace(0, np.nan)) * 100.0

    is_elevated = (spread_z > 0).where(spread_z.notna())
    dpi_min_p = max(1, dpi_window // 2)
    dpi = is_elevated.rolling(window=dpi_window, min_periods=dpi_min_p).mean() * 100.0

    out = pd.DataFrame(
        {
            "Market_Return": market_returns,
            "CSAD": csad,
            "CSSD": cssd,
            "CS_Skewness": cs_skewness,
            "CS_Kurtosis": cs_kurtosis,
            "Spread": spread,
            "Spread_Z": spread_z,
            "CSAD_Z": csad_z,
            "CSSD_Z": cssd_z,
            "DPI": dpi,
            "Downside_Participation": downside_participation,
            "Upside_Participation": upside_participation,
            "Effective_Names": n_eff,
        }
    )
    return stock_returns, out


def fit_rolling_correlation(stock_returns: pd.DataFrame, window: int = 30, refit_every: int = 1, active_nan_threshold: float = 0.2):
    returns = _clean_returns(stock_returns)
    R = returns.values
    T, _ = R.shape
    dates = returns.index
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


def determine_macro_regime(
    metrics: pd.DataFrame,
    dpi_thresh: float = 50.0,
    corr_dist: float = 0.20,
    corr_cap: float = 0.35,
    broad_stress_z: float = 2.0,
    participation_thresh: float = 25.0,
) -> pd.Series:
    """Classify dispersion/correlation state with a broad-selloff override."""
    required = {"DPI", "Ledoit_Correlation", "Market_Return"}
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"Missing columns for macro regime: {sorted(missing)}")

    csad_z = metrics.get("CSAD_Z", pd.Series(np.nan, index=metrics.index))
    downside = metrics.get("Downside_Participation", pd.Series(np.nan, index=metrics.index))
    upside = metrics.get("Upside_Participation", pd.Series(np.nan, index=metrics.index))

    high_dpi = metrics["DPI"] >= dpi_thresh
    low_dpi = metrics["DPI"] < dpi_thresh
    high_corr = metrics["Ledoit_Correlation"] >= corr_cap
    low_corr = metrics["Ledoit_Correlation"] <= corr_dist
    broad_selloff = (
        (metrics["Market_Return"] < 0)
        & (csad_z >= broad_stress_z)
        & (downside >= participation_thresh)
    )
    broad_rally = (
        (metrics["Market_Return"] > 0)
        & (csad_z >= broad_stress_z)
        & (upside >= participation_thresh)
    )

    labels = pd.Series("STOCK_PICKING", index=metrics.index, dtype="object")
    labels.loc[low_dpi & high_corr] = "TRENDING"
    labels.loc[high_dpi & low_corr] = "DISTRIBUTION_TOP"
    labels.loc[high_dpi & high_corr] = "CAPITULATION"
    labels.loc[broad_rally] = "BROAD_RALLY_DISPERSION"
    labels.loc[broad_selloff] = "BROAD_SELLOFF_STRESS"
    return labels


def summarize_dispersion_state(metrics: pd.DataFrame) -> dict[str, float | str]:
    if metrics.empty:
        raise ValueError("Dispersion metrics rỗng sau khi xử lý")

    latest = metrics.iloc[-1]
    spread_z = float(latest.get("Spread_Z", np.nan))
    csad_z = float(latest.get("CSAD_Z", np.nan))
    cssd_z = float(latest.get("CSSD_Z", np.nan))
    dpi = float(latest.get("DPI", np.nan))
    corr = float(latest.get("Ledoit_Correlation", np.nan))
    downside = float(latest.get("Downside_Participation", np.nan))
    market_return = float(latest.get("Market_Return", np.nan))
    broad_stress_score = max(
        0.0,
        min(
            100.0,
            35.0 * max(csad_z, 0.0) / 4.0
            + 25.0 * max(cssd_z, 0.0) / 4.0
            + 25.0 * min(max(downside, 0.0) / 50.0, 1.0)
            + 15.0 * min(abs(min(market_return, 0.0)) / 0.04, 1.0),
        ),
    )
    if broad_stress_score >= 80.0:
        stress_level = "EXTREME"
    elif broad_stress_score >= 60.0:
        stress_level = "HIGH"
    elif broad_stress_score >= 40.0:
        stress_level = "ELEVATED"
    else:
        stress_level = "NORMAL"

    return {
        "methodology_version": METHOD_VERSION,
        "macro_regime": str(latest.get("Macro_Regime", "UNKNOWN")),
        "broad_stress_score": broad_stress_score,
        "broad_stress_level": stress_level,
        "spread_z": spread_z,
        "csad_z": csad_z,
        "cssd_z": cssd_z,
        "dpi": dpi,
        "ledoit_corr": corr,
        "downside_participation": downside,
        "upside_participation": float(latest.get("Upside_Participation", np.nan)),
        "effective_names": float(latest.get("Effective_Names", np.nan)),
    }

