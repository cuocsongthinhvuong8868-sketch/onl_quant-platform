from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


RELATIVE_VALUE_COLUMNS = [
    "peer_median_pb",
    "peer_median_roe",
    "roe_adjusted_fair_pb",
    "market_mispricing_score",
    "relative_valuation_label",
    "relative_value_warning",
]


def _is_valid_number(value: Any) -> bool:
    return pd.notna(value) and np.isfinite(float(value))


def _valid_positive(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values[(values.notna()) & (np.isfinite(values)) & (values > 0)]


def _valid_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values[(values.notna()) & (np.isfinite(values))]


def _regression_slope(data: pd.DataFrame, x_col: str, y_col: str, min_points: int) -> float:
    model_data = data[[x_col, y_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(model_data) < min_points:
        return float("nan")

    x = model_data[x_col].to_numpy(dtype=float)
    y = model_data[y_col].to_numpy(dtype=float)
    x_var = float(np.var(x))
    if x_var <= 1e-12:
        return float("nan")

    slope = float(np.cov(x, y, ddof=0)[0, 1] / x_var)
    return max(-25.0, min(25.0, slope))


def _fallback_roe_adjusted_pb(peer_median_pb: float, row_roe: float, peer_median_roe: float) -> float:
    if not all(_is_valid_number(value) for value in [peer_median_pb, row_roe, peer_median_roe]):
        return float("nan")
    if abs(peer_median_roe) <= 1e-9:
        return peer_median_pb

    roe_delta = (row_roe - peer_median_roe) / abs(peer_median_roe)
    roe_delta = max(-1.0, min(1.0, float(roe_delta)))
    return peer_median_pb * (1.0 + 0.5 * roe_delta)


def _relative_label(mispricing_score: float) -> str:
    if not _is_valid_number(mispricing_score):
        return "Relative Value Unavailable"
    if mispricing_score >= 0.20:
        return "Relatively Cheap"
    if mispricing_score >= 0.05:
        return "Slightly Cheap"
    if mispricing_score <= -0.20:
        return "Relatively Expensive"
    if mispricing_score <= -0.05:
        return "Slightly Expensive"
    return "Peer Fair"


def calculate_relative_value(
    valuation_df: pd.DataFrame,
    min_peers: int = 5,
    min_pb: float = 0.2,
    max_pb: float = 5.0,
) -> pd.DataFrame:
    """
    Add peer-relative valuation fields to a valuation table.

    The relative value check is a secondary sanity check. It compares each
    ticker to same-period peers and estimates a ROE-spread adjusted fair P/B.
    It should not replace the primary RIM or justified P/B valuation.
    """
    result = valuation_df.copy()
    for col in RELATIVE_VALUE_COLUMNS:
        if col == "relative_valuation_label":
            result[col] = "Relative Value Unavailable"
        elif col == "relative_value_warning":
            result[col] = ""
        else:
            result[col] = float("nan")

    if result.empty:
        return result

    required = {"market_pb", "sustainable_roe", "cost_of_equity"}
    missing_required = required - set(result.columns)
    if missing_required:
        result["relative_value_warning"] = (
            "relative value unavailable; missing columns: " + ", ".join(sorted(missing_required))
        )
        return result

    for col in ["market_pb", "sustainable_roe", "cost_of_equity"]:
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result["_roe_spread"] = result["sustainable_roe"] - result["cost_of_equity"]

    grouping = result.groupby("period", dropna=False) if "period" in result.columns else [(None, result)]
    for _, group in grouping:
        for idx, row in group.iterrows():
            peers = group.drop(index=idx)
            peer_pbs = _valid_positive(peers["market_pb"])
            if len(peer_pbs) < min_peers:
                result.at[idx, "relative_value_warning"] = (
                    f"relative value unavailable; only {len(peer_pbs)} peers with valid market P/B"
                )
                continue

            market_pb = row.get("market_pb", float("nan"))
            if not _is_valid_number(market_pb) or market_pb <= 0:
                result.at[idx, "relative_value_warning"] = "relative value unavailable; market P/B missing"
                continue

            peer_median_pb = float(peer_pbs.median())
            peer_roes = _valid_numeric(peers["sustainable_roe"])
            peer_median_roe = float(peer_roes.median()) if not peer_roes.empty else float("nan")
            peer_spreads = _valid_numeric(peers["_roe_spread"])
            peer_median_spread = float(peer_spreads.median()) if not peer_spreads.empty else float("nan")

            row_spread = row.get("_roe_spread", float("nan"))
            slope = _regression_slope(peers, "_roe_spread", "market_pb", min_peers)
            if _is_valid_number(slope) and _is_valid_number(row_spread) and _is_valid_number(peer_median_spread):
                fair_pb = peer_median_pb + slope * (float(row_spread) - peer_median_spread)
            else:
                fair_pb = _fallback_roe_adjusted_pb(peer_median_pb, row.get("sustainable_roe"), peer_median_roe)

            if _is_valid_number(fair_pb):
                fair_pb = max(min_pb, min(max_pb, float(fair_pb)))

            mispricing = float("nan")
            if _is_valid_number(fair_pb):
                mispricing = fair_pb / float(market_pb) - 1.0

            result.at[idx, "peer_median_pb"] = peer_median_pb
            result.at[idx, "peer_median_roe"] = peer_median_roe
            result.at[idx, "roe_adjusted_fair_pb"] = fair_pb
            result.at[idx, "market_mispricing_score"] = mispricing
            result.at[idx, "relative_valuation_label"] = _relative_label(mispricing)

    return result.drop(columns=["_roe_spread"])
