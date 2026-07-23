import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

METHOD_VERSION = "fear_greed_v2.1.0"

_REGIME_BANDS = (
    (0, 20, "EXTREME FEAR"),
    (20, 40, "FEAR"),
    (40, 60, "STOCK PICKING"),
    (60, 80, "GREED"),
    (80, 100, "EXTREME GREED"),
)


def kelly_skewness(x: np.ndarray) -> float:
    """
    Robust non-parametric skewness based on quantiles.

    Formula:
        S = [(P90 - P50) - (P50 - P10)] / (P90 - P10)

    The result is bounded in [-1, 1] and is less sensitive to outliers than
    moment-based skewness.
    """
    arr = pd.Series(x).dropna().values
    if len(arr) < 3:
        return 0.0
    p10, p50, p90 = np.percentile(arr, [10, 50, 90])
    denom = p90 - p10
    return 0.0 if denom == 0 else ((p90 - p50) - (p50 - p10)) / denom


def calculate_risk_score(metrics_df: pd.DataFrame, rank_window: int = 252) -> pd.DataFrame:
    """
    Calculate Fear & Greed score v2 in [0, 100].

    Method v2.1:
    1. Normalize volatility, directional correlations, and CSV with rolling
       percentile ranks. No backfill is used, so early history is not filled
       with future information.
    2. Split sentiment into two auditable forces:
       - Panic pull: high vol + downside crowding + negative skew + dispersion stress.
       - FOMO push: high vol + upside crowding + positive skew + broad upside quality.
    3. Add an acute selloff overlay from 3D/5D PCA market-factor losses. This
       catches margin-call style velocity events that correlation/skew can lag.
    4. Score = 50 + 50 * (FOMO - Panic), apply shock caps, then EWM smoothing.
    5. Return component attribution, regime, confidence, and methodology version.
    """
    if rank_window < 2:
        raise ValueError("rank_window must be at least 2")

    df = metrics_df.copy()
    if df.empty:
        return df

    min_periods = max(2, rank_window // 2)

    def _pct_rank(series: pd.Series) -> pd.Series:
        def _last_percentile(window: pd.Series) -> float:
            if pd.isna(window.iloc[-1]):
                return np.nan
            valid = window.dropna()
            if len(valid) < min_periods:
                return np.nan
            return float(valid.rank(pct=True).iloc[-1])

        return (
            series.rolling(window=rank_window, min_periods=min_periods)
            .apply(_last_percentile)
            .ffill()
        )

    df["Vol_Norm"] = _pct_rank(df["EGARCH_Vol"])
    df["Down_Corr_Norm"] = _pct_rank(df["Downside_Corr"])
    df["Up_Corr_Norm"] = _pct_rank(df["Upside_Corr"])
    df["CSV_Norm"] = _pct_rank(df["CSV_Index"])

    df["Market_Impulse_3D"] = df["Market_Factor"].rolling(3, min_periods=3).sum()
    df["Market_Impulse_5D"] = df["Market_Factor"].rolling(5, min_periods=5).sum()
    shock_3d = (-df["Market_Impulse_3D"]).clip(lower=0)
    shock_5d = (-df["Market_Impulse_5D"]).clip(lower=0)
    rally_3d = df["Market_Impulse_3D"].clip(lower=0)
    rally_5d = df["Market_Impulse_5D"].clip(lower=0)

    df["Shock_3D_Norm"] = _pct_rank(shock_3d).where(shock_3d > 0, 0.0)
    df["Shock_5D_Norm"] = _pct_rank(shock_5d).where(shock_5d > 0, 0.0)
    df["Rally_3D_Norm"] = _pct_rank(rally_3d).where(rally_3d > 0, 0.0)
    df["Rally_5D_Norm"] = _pct_rank(rally_5d).where(rally_5d > 0, 0.0)
    df["Acute_Shock"] = pd.concat(
        [df["Shock_3D_Norm"], df["Shock_5D_Norm"]], axis=1
    ).max(axis=1)
    df["Positive_Impulse"] = pd.concat(
        [df["Rally_3D_Norm"], df["Rally_5D_Norm"]], axis=1
    ).max(axis=1)

    df["Vol_Pressure"] = df["Vol_Norm"].clip(0, 1)
    df["Downside_Crowding"] = df["Down_Corr_Norm"].clip(0, 1)
    df["Upside_Crowding"] = df["Up_Corr_Norm"].clip(0, 1)
    df["Dispersion_Stress"] = df["CSV_Norm"].clip(0, 1)
    df["Acute_Shock"] = df["Acute_Shock"].clip(0, 1)
    df["Positive_Impulse"] = df["Positive_Impulse"].clip(0, 1)

    negative_skew = df["Skewness"].clip(upper=0).abs().clip(0, 1)
    positive_skew = df["Skewness"].clip(lower=0).clip(0, 1)
    broad_upside_quality = (1.0 - df["Dispersion_Stress"]).clip(0, 1)
    negative_impulse = (
        (df["Market_Impulse_3D"] < 0) | (df["Market_Impulse_5D"] < 0)
    ).astype(float)
    positive_impulse = (
        (df["Market_Impulse_3D"] > 0) | (df["Market_Impulse_5D"] > 0)
    ).astype(float)

    df["Panic_Pull"] = (
        0.24 * df["Vol_Pressure"]
        + 0.22 * df["Downside_Crowding"]
        + 0.18 * negative_skew
        + 0.14 * df["Dispersion_Stress"]
        + 0.22 * df["Acute_Shock"] * negative_impulse
    ).clip(0, 1)
    df["Fomo_Push"] = (
        0.20 * df["Vol_Pressure"]
        + 0.28 * df["Upside_Crowding"]
        + 0.22 * positive_skew
        + 0.15 * broad_upside_quality
        + 0.15 * df["Positive_Impulse"] * positive_impulse
    ).clip(0, 1)

    df["Net_Sentiment_Pressure"] = (df["Fomo_Push"] - df["Panic_Pull"]).clip(-1, 1)
    base_score = (50 + 50 * df["Net_Sentiment_Pressure"]).clip(0, 100)
    df["Shock_Score_Cap"] = np.select(
        [
            df["Acute_Shock"] >= 0.985,
            df["Acute_Shock"] >= 0.950,
            df["Acute_Shock"] >= 0.900,
        ],
        [25.0, 35.0, 45.0],
        default=100.0,
    )
    df["Shock_Regime_Flag"] = np.select(
        [
            df["Acute_Shock"] >= 0.985,
            df["Acute_Shock"] >= 0.950,
            df["Acute_Shock"] >= 0.900,
        ],
        ["MARGIN_CALL_RISK", "ACUTE_SELLOFF", "SELL_OFF_WATCH"],
        default="NONE",
    )
    df["Risk_Score_Raw"] = base_score.where(
        negative_impulse == 0,
        np.minimum(base_score, df["Shock_Score_Cap"]),
    ).clip(0, 100)
    df["Risk_Score"] = df["Risk_Score_Raw"].ewm(span=5, adjust=False).mean()

    dominant_pressure = pd.concat([df["Panic_Pull"], df["Fomo_Push"]], axis=1).max(axis=1)
    directional_gap = (df["Fomo_Push"] - df["Panic_Pull"]).abs()
    pressure_balance = (directional_gap / dominant_pressure.replace(0, np.nan)).fillna(0.0)
    df["Signal_Confidence"] = (
        0.20 + 0.50 * dominant_pressure + 0.30 * pressure_balance
    ).clip(0, 1)
    df["Sentiment_Regime"] = df["Risk_Score"].map(_classify_regime)
    df["Methodology_Version"] = METHOD_VERSION

    valid_score = df["Risk_Score"].dropna()
    if not valid_score.empty:
        logger.info(
            "Risk Score v2 — current: %.1f | range [%.1f, %.1f]",
            valid_score.iloc[-1],
            valid_score.tail(252).min(),
            valid_score.tail(252).max(),
        )
    return df


def _classify_regime(score: float) -> str:
    if pd.isna(score):
        return "INSUFFICIENT_DATA"
    bounded_score = min(max(float(score), 0.0), 100.0)
    for lo, hi, label in _REGIME_BANDS:
        if lo <= bounded_score < hi or (bounded_score >= 100 and hi == 100):
            return label
    return "EXTREME GREED"
