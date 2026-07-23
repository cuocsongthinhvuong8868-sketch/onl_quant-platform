"""Snapshot hook for the Credit Spread report engine."""
from __future__ import annotations

from typing import Any

import pandas as pd

from tools.credit_spread.ai_analysis import load_canonical_snapshot


def _round_optional(value: Any, digits: int) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def snapshot(df_close=None, load_custom=None) -> dict:
    canonical = load_canonical_snapshot()
    return {
        "snapshot_date": canonical["data_date_iso"],
        "display_date": canonical["date"],
        "bank_yield_pct": round(float(canonical["bank_yield_pct"]), 4),
        "real_estate_yield_pct": round(float(canonical["real_estate_yield_pct"]), 4),
        "signed_spread_pct": round(float(canonical["signed_spread_pct"]), 4),
        "risk_premium_bps": round(float(canonical["risk_premium_bps"]), 2),
        "risk_premium_change_bps": _round_optional(canonical["risk_premium_change_bps"], 2),
        "risk_premium_change_3p_bps": _round_optional(
            canonical["risk_premium_change_3p_bps"],
            2,
        ),
        "risk_premium_percentile": round(float(canonical["risk_premium_percentile"]), 2),
        "risk_premium_history_zscore": _round_optional(
            canonical["risk_premium_history_zscore"],
            4,
        ),
        "direction": canonical["direction"],
        "trend_3p": canonical["trend_3p"],
        "matched_periods": int(canonical["matched_periods"]),
        "bank_issuance_count": int(canonical["bank_issuance_count"]),
        "real_estate_issuance_count": int(canonical["real_estate_issuance_count"]),
        "bank_coupon_coverage_pct": round(float(canonical["bank_coupon_coverage_pct"]), 2),
        "real_estate_coupon_coverage_pct": round(
            float(canonical["real_estate_coupon_coverage_pct"]),
            2,
        ),
        "data_quality": canonical["data_quality"],
        "weighting": canonical["weighting"],
        "maturity_scope": canonical["maturity_scope"],
        "status": "ok",
        "error": "",
    }
