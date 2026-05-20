"""
scoring.py — Cross-sectional z-score, sector-neutralize, composite ranking.

Pipeline:
  raw factor → cross-section z-score → sector-neutralize (subtract sector mean)
             → equal-weight composite → percentile rank

Sector mapping từ ticker_metadata.csv (ICB industry_name). Sector <5 mã gộp 'Other'.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SECTOR_SIZE = 5
OTHER_SECTOR = "Other"


def xs_zscore(factors: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score mỗi column (factor) độc lập.

    Robust: dùng (x - median) / MAD * 1.4826 thay vì mean/std để giảm outlier impact.
    Fallback về mean/std nếu MAD=0.
    """
    z = pd.DataFrame(index=factors.index, columns=factors.columns, dtype=float)
    for col in factors.columns:
        s = factors[col].astype(float)
        valid = s.dropna()
        if valid.empty:
            z[col] = np.nan
            continue
        med = valid.median()
        mad = (valid - med).abs().median()
        if mad > 0:
            z[col] = (s - med) / (mad * 1.4826)
        else:
            # Fallback mean/std
            mu, sd = valid.mean(), valid.std()
            z[col] = (s - mu) / sd if sd > 0 else 0.0
    # Winsorize ±3σ
    z = z.clip(lower=-3.0, upper=3.0)
    return z


def build_sector_map(
    metadata: pd.DataFrame | None,
    universe: list[str],
) -> pd.Series:
    """Map ticker → sector. Gộp sector <5 mã thành 'Other'. Trả về Series index=ticker.

    Nếu metadata None hoặc không có ICB → tất cả về 'Other'.
    """
    if metadata is None or metadata.empty:
        return pd.Series(OTHER_SECTOR, index=universe)

    industry_col = None
    for cand in ("industry_name", "industry", "icb_industry", "sector"):
        if cand in metadata.columns:
            industry_col = cand
            break
    if industry_col is None:
        return pd.Series(OTHER_SECTOR, index=universe)

    raw_map = metadata[industry_col].reindex(universe)
    raw_map = raw_map.fillna(OTHER_SECTOR)

    # Count + gộp sector <5
    counts = raw_map.value_counts()
    small_sectors = counts[counts < MIN_SECTOR_SIZE].index.tolist()
    raw_map = raw_map.where(~raw_map.isin(small_sectors), OTHER_SECTOR)

    return raw_map


def sector_neutralize(z: pd.DataFrame, sector_map: pd.Series) -> pd.DataFrame:
    """Subtract sector mean từ mỗi factor z. Preserve NaN positions."""
    aligned_sectors = sector_map.reindex(z.index).fillna(OTHER_SECTOR)
    z_neutral = z.copy()
    for col in z.columns:
        sector_mean = z[col].groupby(aligned_sectors).transform("mean")
        z_neutral[col] = z[col] - sector_mean
    return z_neutral


def composite_score(
    z_neutral: pd.DataFrame,
    factor_weights: dict[str, float] | None = None,
) -> pd.Series:
    """Equal-weight (default) composite score = mean of z-scores.

    Mã có >=5 factor NaN (out of 10) → composite = NaN (insufficient data).
    """
    if factor_weights is None:
        weights = pd.Series(1.0, index=z_neutral.columns)
    else:
        weights = pd.Series(factor_weights).reindex(z_neutral.columns).fillna(0.0)
    weights = weights / weights.sum()  # normalize

    # Per-row weighted mean ignore NaN, nhưng require ít nhất 5 factor valid
    n_valid = z_neutral.notna().sum(axis=1)
    weighted = z_neutral.mul(weights, axis=1)
    composite = weighted.sum(axis=1, min_count=1) / n_valid.where(n_valid > 0, np.nan) * len(weights)
    # Mã <5 factor → mask NaN
    composite = composite.where(n_valid >= 5)
    return composite


def percentile_rank(composite: pd.Series) -> pd.Series:
    """Convert composite → percentile 0-100 (cross-section)."""
    return composite.rank(pct=True) * 100.0


def build_score_table(
    factors: pd.DataFrame,
    metadata: pd.DataFrame | None,
    sector_neutral: bool = True,
) -> dict:
    """Full pipeline: factor raw → z → (sector-neutral) → composite → rank.

    Returns dict với keys:
        - raw: pd.DataFrame factor raw values
        - z: pd.DataFrame z-scores (sau sector-neutral nếu enabled)
        - sector_map: pd.Series ticker → sector
        - composite: pd.Series ticker → composite z-score
        - rank_pct: pd.Series ticker → percentile 0-100
    """
    z_xs = xs_zscore(factors)
    sector_map = build_sector_map(metadata, list(factors.index))

    if sector_neutral:
        z_final = sector_neutralize(z_xs, sector_map)
    else:
        z_final = z_xs

    composite = composite_score(z_final)
    rank_pct = percentile_rank(composite)

    return {
        "raw": factors,
        "z": z_final,
        "sector_map": sector_map,
        "composite": composite,
        "rank_pct": rank_pct,
    }
