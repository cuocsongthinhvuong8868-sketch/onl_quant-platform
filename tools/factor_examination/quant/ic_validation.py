"""
ic_validation.py — Forward Information Coefficient backtest.

IC = Spearman rank correlation giữa composite_t và forward return_{t, t+h}.
Multiple horizons (21/63/126 days = 1M/3M/6M).

Pipeline (vector hoá):
  1. Snapshot date list (mỗi 21 phiên trong lookback)
  2. Per snapshot: compute factor + composite → forward return
  3. Spearman corr per snapshot
  4. Average IC + hit rate + decile spread (top10% vs bot10% cumulative)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .factors import compute_all_factors, MIN_BARS_FULL
from .scoring import build_score_table

HORIZONS = (21, 63, 126)
SNAPSHOT_STEP = 21  # 1 month spacing


def _spearman_ic(x: pd.Series, y: pd.Series) -> float:
    """Spearman rank correlation. NaN-robust."""
    common = x.dropna().index.intersection(y.dropna().index)
    if len(common) < 10:
        return np.nan
    return float(x.loc[common].rank().corr(y.loc[common].rank()))


def run_ic_backtest(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    market: pd.Series,
    metadata: pd.DataFrame | None,
    sector_neutral: bool = True,
    lookback_years: int = 3,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict:
    """Run rolling snapshot IC backtest.

    Returns dict:
        - ic_series: DataFrame index=snapshot_date, columns=horizons → IC value
        - ic_summary: DataFrame stat per horizon (mean IC, hit rate, ICIR)
        - decile_cum: DataFrame index=date, columns=[top_decile, bot_decile, spread] (1M forward)
    """
    if len(prices) < MIN_BARS_FULL + max(horizons) + SNAPSHOT_STEP:
        raise ValueError(
            f"Cần ít nhất {MIN_BARS_FULL + max(horizons) + SNAPSHOT_STEP} bars, "
            f"chỉ có {len(prices)}"
        )

    end = prices.index[-1]
    start = end - pd.Timedelta(days=int(lookback_years * 365))
    # Snapshot dates: từ start trở đi, cách nhau SNAPSHOT_STEP, không vượt end - max(horizons)
    eligible_idx = prices.index[(prices.index >= start) & (prices.index <= end - pd.Timedelta(days=max(horizons) + 7))]
    if len(eligible_idx) == 0:
        raise ValueError("Không đủ snapshot date trong lookback")

    snapshot_dates = eligible_idx[::SNAPSHOT_STEP]

    ic_rows = []
    decile_rows = []
    for snap_date in snapshot_dates:
        prices_snap = prices.loc[:snap_date]
        volumes_snap = volumes.loc[:snap_date]
        market_snap = market.loc[:snap_date]
        if len(prices_snap) < MIN_BARS_FULL:
            continue

        try:
            factors = compute_all_factors(prices_snap, volumes_snap, market_snap)
            scored = build_score_table(factors, metadata, sector_neutral=sector_neutral)
            composite = scored["composite"]
        except Exception:
            continue

        # Forward returns
        row = {"date": snap_date}
        for h in horizons:
            fwd_end_idx = prices.index.get_indexer([snap_date])[0] + h
            if fwd_end_idx >= len(prices):
                row[f"ic_{h}d"] = np.nan
                continue
            fwd_end = prices.index[fwd_end_idx]
            fwd_ret = prices.loc[fwd_end] / prices.loc[snap_date] - 1.0
            row[f"ic_{h}d"] = _spearman_ic(composite, fwd_ret)
        ic_rows.append(row)

        # Decile spread (21d forward — only for primary horizon)
        fwd_end_idx = prices.index.get_indexer([snap_date])[0] + 21
        if fwd_end_idx < len(prices):
            fwd_end = prices.index[fwd_end_idx]
            fwd_ret = prices.loc[fwd_end] / prices.loc[snap_date] - 1.0
            valid = composite.dropna()
            if len(valid) >= 30:
                # Top 10% vs Bot 10%
                quantiles = valid.quantile([0.1, 0.9])
                top = valid[valid >= quantiles[0.9]].index
                bot = valid[valid <= quantiles[0.1]].index
                top_ret = fwd_ret.reindex(top).mean()
                bot_ret = fwd_ret.reindex(bot).mean()
                decile_rows.append({
                    "date": snap_date,
                    "top_decile_ret": float(top_ret) if pd.notna(top_ret) else np.nan,
                    "bot_decile_ret": float(bot_ret) if pd.notna(bot_ret) else np.nan,
                    "spread": float(top_ret - bot_ret) if pd.notna(top_ret) and pd.notna(bot_ret) else np.nan,
                })

    if not ic_rows:
        raise ValueError("Không có snapshot nào valid")

    ic_df = pd.DataFrame(ic_rows).set_index("date")

    # Summary
    summary_rows = []
    for h in horizons:
        col = f"ic_{h}d"
        ic_vals = ic_df[col].dropna()
        if ic_vals.empty:
            continue
        mean_ic = ic_vals.mean()
        std_ic = ic_vals.std()
        hit_rate = (ic_vals > 0).mean()
        icir = mean_ic / std_ic if std_ic > 0 else np.nan
        summary_rows.append({
            "horizon_days": h,
            "n_snapshots": int(len(ic_vals)),
            "mean_ic": mean_ic,
            "std_ic": std_ic,
            "ICIR": icir,
            "hit_rate": hit_rate,
        })
    summary_df = pd.DataFrame(summary_rows)

    # Decile cumulative
    if decile_rows:
        decile_df = pd.DataFrame(decile_rows).set_index("date").sort_index()
        decile_df["top_cum"] = (1.0 + decile_df["top_decile_ret"].fillna(0)).cumprod()
        decile_df["bot_cum"] = (1.0 + decile_df["bot_decile_ret"].fillna(0)).cumprod()
        decile_df["spread_cum"] = decile_df["top_cum"] - decile_df["bot_cum"]
    else:
        decile_df = pd.DataFrame()

    return {
        "ic_series": ic_df,
        "ic_summary": summary_df,
        "decile_cum": decile_df,
    }
