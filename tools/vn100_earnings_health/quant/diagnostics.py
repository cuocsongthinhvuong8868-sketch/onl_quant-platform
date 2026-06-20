from __future__ import annotations

import json
import numpy as np
import pandas as pd

from .config import CFO_TO_LNST_THRESHOLD, HIGH_STRESS_THRESHOLD


def flags_for_row(row: pd.Series) -> list[str]:
    flags: list[str] = []

    healthy_growth = (
        row.get("ttm_revenue_yoy", np.nan) > 0
        and row.get("ttm_net_profit_yoy", np.nan) > 0
        and row.get("ttm_cfo", np.nan) > 0
        and row.get("cfo_to_net_profit", np.nan) >= CFO_TO_LNST_THRESHOLD
        and row.get("working_capital_stress_score", 50) < HIGH_STRESS_THRESHOLD
        and row.get("leverage_stress_score", 50) < HIGH_STRESS_THRESHOLD
    )
    if healthy_growth:
        flags.append("Healthy Growth")

    accounting_profit_risk = (
        row.get("ttm_net_profit_yoy", np.nan) > 0
        and (
            row.get("ttm_cfo_yoy", np.nan) < 0
            or row.get("cfo_to_net_profit", np.nan) < CFO_TO_LNST_THRESHOLD
            or row.get("cash_accrual_ratio_score", 50) < 30
        )
    )
    if accounting_profit_risk:
        flags.append("Accounting Profit Risk")

    wc_absorption = (
        row.get("ttm_revenue_yoy", np.nan) > 0
        and (
            row.get("receivables_growth_spread", np.nan) > 0.10
            or row.get("inventory_growth_spread", np.nan) > 0.10
        )
        and (
            row.get("ttm_cfo_yoy", np.nan) < 0
            or row.get("cfo_margin", np.nan) < 0
        )
    )
    if wc_absorption:
        flags.append("Working Capital Absorption")

    leverage_funded = (
        row.get("ttm_revenue_yoy", np.nan) > 0
        and row.get("total_debt_yoy", np.nan) > row.get("ttm_revenue_yoy", np.nan) + 0.10
        and (row.get("ttm_cfo", np.nan) < 0 or row.get("ttm_cfo_yoy", np.nan) < 0)
    ) or (
        row.get("ttm_interest_expense_yoy", np.nan)
        > row.get("ttm_ebit_yoy", np.nan) + 0.10
    )
    if leverage_funded:
        flags.append("Leverage-Funded Growth")

    margin_compression = (
        row.get("ttm_revenue_yoy", np.nan) > 0
        and (
            row.get("gross_margin_yoy_delta", np.nan) < -0.01
            or row.get("ebit_margin_yoy_delta", np.nan) < -0.01
        )
    )
    if margin_compression:
        flags.append("Margin Compression")

    if row.get("working_capital_stress_score", 0) >= HIGH_STRESS_THRESHOLD:
        flags.append("High Working Capital Stress")
    if row.get("leverage_stress_score", 0) >= HIGH_STRESS_THRESHOLD:
        flags.append("High Leverage Stress")
    if row.get("matrix_consistency_score", 100) < 40:
        flags.append("Internal Consistency Breakdown")

    return flags


def add_company_flags(scored: pd.DataFrame) -> pd.DataFrame:
    out = scored.copy()
    out["diagnostic_flags"] = out.apply(flags_for_row, axis=1)
    out["primary_flag"] = out["diagnostic_flags"].map(lambda flags: flags[0] if flags else "No Major Flag")
    out["flag_count"] = out["diagnostic_flags"].map(len)
    return out


def build_diagnostic_json(scored: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in scored.iterrows():
        flags = row.get("diagnostic_flags", [])
        if isinstance(flags, str):
            try:
                flags = json.loads(flags)
            except Exception:
                flags = [flags]
        if not flags:
            continue
        records.append(
            {
                "ticker": row["ticker"],
                "period": row["period"],
                "sector": row.get("sector"),
                "corporate_health_score": row.get("corporate_health_score"),
                "diagnostic_flags": flags,
            }
        )
    return records


def build_alerts(scored: pd.DataFrame) -> pd.DataFrame:
    latest_order = scored["period_order"].max()
    latest = scored[scored["period_order"] == latest_order].copy()
    if latest.empty:
        return pd.DataFrame()
    alert_mask = (
        (latest["flag_count"] >= 2)
        | (latest["corporate_health_score"] < 35)
        | (latest["working_capital_stress_score"] >= HIGH_STRESS_THRESHOLD)
        | (latest["leverage_stress_score"] >= HIGH_STRESS_THRESHOLD)
    )
    alerts = latest.loc[alert_mask, [
        "ticker",
        "company_name",
        "sector",
        "period",
        "corporate_health_score",
        "working_capital_stress_score",
        "leverage_stress_score",
        "matrix_consistency_score",
        "primary_flag",
        "flag_count",
    ]].copy()
    alerts["alert_level"] = np.select(
        [
            alerts["corporate_health_score"] < 30,
            alerts["flag_count"] >= 3,
            alerts["working_capital_stress_score"] >= HIGH_STRESS_THRESHOLD,
            alerts["leverage_stress_score"] >= HIGH_STRESS_THRESHOLD,
        ],
        ["Critical", "High", "Medium", "Medium"],
        default="Watch",
    )
    return alerts.sort_values(
        ["alert_level", "corporate_health_score"], ascending=[True, True]
    ).reset_index(drop=True)
