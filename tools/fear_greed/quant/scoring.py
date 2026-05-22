import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def kelly_skewness(x: np.ndarray) -> float:
    """
    Skewness phi tham số dựa trên phân vị (robust).

    Công thức
    ---------
        S = [(P90 − P50) − (P50 − P10)] / (P90 − P10)

    Ưu điểm so với pandas .skew()
    ------------------------------
    - Giới hạn trong [−1, 1] — không bị thổi phồng bởi outlier.
    - Dùng order statistics, 1 điểm cực đoan không làm lệch cả cửa sổ.
    """
    arr = pd.Series(x).dropna().values
    if len(arr) < 3:
        return 0.0
    p10, p50, p90 = np.percentile(arr, [10, 50, 90])
    denom = p90 - p10
    return 0.0 if denom == 0 else ((p90 - p50) - (p50 - p10)) / denom


def calculate_risk_score(metrics_df: pd.DataFrame, rank_window: int = 252) -> pd.DataFrame:
    """
    Tính Fear & Greed score trong [0, 100] từ các metrics định lượng.

    Phương pháp
    -----------
    1. Rolling percentile rank (rank_window ngày) cho vol và correlation
       → tránh bóp méo scale do outlier (MinMaxScaler bị lỗi này).
    2. Phân rã tâm lý:
         panic_pull = Vol_Rank × DownCorr_Rank × |Kelly skew âm|
         fomo_push  = Vol_Rank × UpCorr_Rank   × Kelly skew dương
    3. Mapping sang [0, 100]:
         score < 50 → Fear   (panic_pull lớn hơn)
         score > 50 → Greed  (fomo_push lớn hơn)
    4. EWM smoothing (span=5) để bớt nhiễu ngày.

    Fully vectorised — không dùng iterrows.
    """
    df = metrics_df.copy()

    def _pct_rank(s: pd.Series) -> pd.Series:
        return (
            s.rolling(window=rank_window, min_periods=rank_window // 2)
             .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
             .ffill()
        )

    df["Vol_Norm"]       = _pct_rank(df["EGARCH_Vol"])
    df["Down_Corr_Norm"] = _pct_rank(df["Downside_Corr"])
    df["Up_Corr_Norm"]   = _pct_rank(df["Upside_Corr"])
    df.bfill(inplace=True)

    panic_pull = (df["Vol_Norm"] * df["Down_Corr_Norm"] * df["Skewness"].clip(upper=0).abs()) ** (1/3)
    fomo_push  = (df["Vol_Norm"] * df["Up_Corr_Norm"]   * df["Skewness"].clip(lower=0)) ** (1/3)

    df["Risk_Score"] = np.where(
        panic_pull > fomo_push,
        50 - 50 * panic_pull,
        50 + 50 * fomo_push,
    )
    df["Risk_Score"] = df["Risk_Score"].ewm(span=5, adjust=False).mean()

    logger.info("Risk Score — hiện tại: %.1f | range [%.1f, %.1f]",
                df["Risk_Score"].iloc[-1],
                df["Risk_Score"].tail(252).min(),
                df["Risk_Score"].tail(252).max())
    return df
