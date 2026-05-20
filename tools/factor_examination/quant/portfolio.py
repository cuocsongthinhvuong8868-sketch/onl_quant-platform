"""
portfolio.py — Aggregate per-ticker factor exposures lên portfolio level.

Input: holdings = dict[ticker, weight] (weight normalize → 1.0)
Output:
  - factor_exposure: weighted sum của z-scores (10 chiều)
  - composite: weighted composite z
  - holdings_table: per-ticker rank + composite + top/weak factor
  - concentration: tilt nào > +1σ hoặc < -1σ
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_weights(holdings: dict[str, float]) -> dict[str, float]:
    """Normalize weights → tổng = 1.0. Drop weight <= 0."""
    cleaned = {t: float(w) for t, w in holdings.items() if w is not None and float(w) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("Tất cả weight = 0 hoặc âm")
    return {t: w / total for t, w in cleaned.items()}


def parse_holdings_text(text: str) -> dict[str, float]:
    """Parse text dạng 'VIC,0.2\nVHM,0.15\n...' hoặc 'VIC 0.2 / VHM 0.15'.

    Hỗ trợ separator: comma, tab, space. Hỗ trợ % (chuyển về fraction).
    """
    if not text or not text.strip():
        return {}

    holdings = {}
    for raw_line in text.strip().split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Try CSV row first
        parts = line.replace("\t", ",").replace(" ", ",").split(",")
        parts = [p for p in parts if p.strip()]
        if len(parts) < 2:
            continue
        ticker = parts[0].strip().upper()
        w_str = parts[1].strip()
        if w_str.endswith("%"):
            w = float(w_str.rstrip("%")) / 100.0
        else:
            w = float(w_str)
        holdings[ticker] = w
    return holdings


def parse_holdings_csv(file_bytes: bytes) -> dict[str, float]:
    """Parse uploaded CSV file (ticker, weight). Tolerant với header variations."""
    import io
    df = pd.read_csv(io.BytesIO(file_bytes))
    if len(df.columns) < 2:
        raise ValueError("CSV cần ít nhất 2 column: ticker, weight")
    # Try detect ticker / weight columns
    ticker_col, weight_col = df.columns[0], df.columns[1]
    for cand in ("ticker", "Ticker", "symbol", "Symbol", "Mã"):
        if cand in df.columns:
            ticker_col = cand
            break
    for cand in ("weight", "Weight", "tỷ trọng", "Tỷ trọng", "pct", "%"):
        if cand in df.columns:
            weight_col = cand
            break
    holdings = {}
    for _, row in df.iterrows():
        t = str(row[ticker_col]).strip().upper()
        if not t or t == "NAN":
            continue
        try:
            w = float(row[weight_col])
        except (TypeError, ValueError):
            continue
        if w > 1.5:
            # Heuristic: nếu giá trị >1.5 → user đang dùng % (15 thay 0.15)
            w = w / 100.0
        if w > 0:
            holdings[t] = w
    return holdings


def aggregate_portfolio(
    holdings_norm: dict[str, float],
    z_table: pd.DataFrame,
    composite: pd.Series,
    rank_pct: pd.Series,
    sector_map: pd.Series,
) -> dict:
    """Compute portfolio-level metrics.

    Returns:
        factor_exposure: pd.Series — weighted sum z per factor (10 chiều)
        portfolio_composite: float — weighted composite z
        holdings_table: pd.DataFrame — per-ticker breakdown
        concentration: pd.Series — factor có |exposure| > 1.0
        sector_weights: pd.Series — tổng weight per sector
        missing: list[str] — ticker không có trong universe
    """
    weights = pd.Series(holdings_norm)
    universe_tickers = z_table.index
    in_universe = weights.index.intersection(universe_tickers)
    missing = weights.index.difference(universe_tickers).tolist()

    if len(in_universe) == 0:
        raise ValueError(f"Không có holding nào trong universe (missing: {missing})")

    w_valid = weights.loc[in_universe]
    # Renormalize nếu có missing
    w_valid = w_valid / w_valid.sum()

    # Factor exposure: Σ w_i * z_i,k
    z_sub = z_table.loc[in_universe]
    factor_exposure = z_sub.mul(w_valid, axis=0).sum(axis=0, min_count=1)

    # Portfolio composite
    comp_sub = composite.loc[in_universe]
    portfolio_composite = float((comp_sub * w_valid).sum(skipna=True))

    # Per-holding table
    rows = []
    for t in in_universe:
        row_z = z_sub.loc[t]
        if row_z.notna().any():
            valid = row_z.dropna()
            top_factor = valid.idxmax()
            top_value = valid.max()
            weak_factor = valid.idxmin()
            weak_value = valid.min()
        else:
            top_factor = weak_factor = "—"
            top_value = weak_value = np.nan
        rows.append({
            "ticker": t,
            "weight": float(w_valid.loc[t]),
            "composite_z": float(comp_sub.loc[t]) if pd.notna(comp_sub.loc[t]) else np.nan,
            "rank_pct": float(rank_pct.loc[t]) if pd.notna(rank_pct.loc[t]) else np.nan,
            "sector": sector_map.loc[t] if t in sector_map.index else "—",
            "top_factor": top_factor,
            "top_z": top_value,
            "weak_factor": weak_factor,
            "weak_z": weak_value,
        })
    holdings_table = pd.DataFrame(rows).sort_values("composite_z", ascending=False, na_position="last")

    # Concentration: factor có |exposure| > 1.0
    concentration = factor_exposure[factor_exposure.abs() > 1.0]

    # Sector weights
    sectors_in_port = sector_map.reindex(in_universe).fillna("Other")
    sector_weights = w_valid.groupby(sectors_in_port).sum().sort_values(ascending=False)

    return {
        "factor_exposure": factor_exposure,
        "portfolio_composite": portfolio_composite,
        "holdings_table": holdings_table,
        "concentration": concentration,
        "sector_weights": sector_weights,
        "missing": missing,
    }


def find_peers(
    ticker: str,
    z_table: pd.DataFrame,
    sector_map: pd.Series,
    n: int = 10,
) -> pd.DataFrame:
    """Find n peers gần nhất với ticker theo Euclidean distance trong factor space.

    Optionally restrict same-sector peers (configurable bởi caller — đây trả về all).
    """
    if ticker not in z_table.index:
        raise ValueError(f"{ticker} không có trong universe")

    target_vec = z_table.loc[ticker]
    if target_vec.isna().all():
        raise ValueError(f"{ticker} có toàn NaN factor")

    # Replace NaN với 0 cho cả 2 phía (tương đương "neutral" gap)
    target_filled = target_vec.fillna(0.0)
    z_filled = z_table.fillna(0.0)
    diffs = z_filled - target_filled
    dist = np.sqrt((diffs ** 2).sum(axis=1))
    dist = dist.drop(ticker, errors="ignore").sort_values()

    rows = []
    for peer, d in dist.head(n).items():
        rows.append({
            "peer": peer,
            "distance": float(d),
            "sector": sector_map.loc[peer] if peer in sector_map.index else "—",
        })
    return pd.DataFrame(rows)
