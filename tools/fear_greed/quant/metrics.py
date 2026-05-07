import logging
import numpy as np
import pandas as pd

from tools.fear_greed.quant.factors    import extract_market_factor_pca
from tools.fear_greed.quant.volatility import fit_egarch
from tools.fear_greed.quant.scoring    import kelly_skewness

logger = logging.getLogger(__name__)


def calculate_quant_metrics(df_stocks: pd.DataFrame, window_size: int) -> pd.DataFrame:
    """
    Pipeline định lượng đầy đủ: giá đóng cửa → DataFrame metrics.

    Các giai đoạn
    -------------
    1. Tính daily returns
    2. PCA Market Factor (loại bias vốn hóa)
    3. EGARCH(1,1,1) Skewed-T conditional volatility
    4. Rolling Kelly Skewness
    5. Directional correlation (downside / upside)
    6. Cross-Sectional Volatility Index (CSV)

    Parameters
    ----------
    df_stocks   : DataFrame giá đóng cửa (ngày × mã)
    window_size : cửa sổ cuộn cho skewness, beta, CSV, EWM halflife

    Returns
    -------
    DataFrame với các cột: Market_Factor, EGARCH_Vol, Skewness,
    Downside_Corr, Upside_Corr, CSV_Index

    Raises
    ------
    RuntimeError : từ fit_egarch nếu model không hội tụ
    """
    stocks_ret = df_stocks.pct_change().dropna(how="all")
    logger.info("Pipeline metrics — %d ngày × %d mã", *stocks_ret.shape)

    # 1 — Market Factor
    mf = extract_market_factor_pca(stocks_ret)

    # 2 — Conditional Volatility
    egarch_vol = fit_egarch(mf)

    # 3 — Rolling Kelly Skewness
    rolling_skew = (
        mf.rolling(window=window_size, min_periods=window_size // 2)
          .apply(kelly_skewness)
          .ffill()
    )

    # 4 — Directional Correlations
    down_mask = mf < 0
    up_mask   = mf > 0

    downside_corr = (
        stocks_ret.where(down_mask, np.nan)
        .ewm(halflife=window_size, min_periods=15)
        .corr(mf.where(down_mask, np.nan))
        .median(axis=1).ffill()
    )
    upside_corr = (
        stocks_ret.where(up_mask, np.nan)
        .ewm(halflife=window_size, min_periods=15)
        .corr(mf.where(up_mask, np.nan))
        .median(axis=1).ffill()
    )

    # 5 — Cross-Sectional Volatility
    roll_var_m = mf.rolling(window=window_size).var()
    roll_beta  = stocks_ret.rolling(window=window_size).cov(mf).div(roll_var_m, axis=0)
    idio_var   = (
        stocks_ret.rolling(window=window_size).var()
        - roll_beta.pow(2).multiply(roll_var_m, axis=0)
    ).clip(lower=0)
    csv_index = idio_var.median(axis=1).ffill()

    metrics_df = pd.DataFrame({
        "Market_Factor": mf,
        "EGARCH_Vol":    egarch_vol,
        "Skewness":      rolling_skew,
        "Downside_Corr": downside_corr,
        "Upside_Corr":   upside_corr,
        "CSV_Index":     csv_index,
    }).dropna()

    logger.info("Metrics xong — %d ngày hợp lệ.", len(metrics_df))
    return metrics_df
