from __future__ import annotations

import json
import numpy as np
import pandas as pd

from .config import CORE_COLUMNS, HEALTH_CORE_COLUMNS


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if valid.sum() == 0:
        return values.mean()
    return float(np.average(values[valid], weights=weights[valid]))


def diffusion_label(score: float, trend: float) -> str:
    if pd.isna(score):
        return "Insufficient Data"
    if score >= 65 and (pd.isna(trend) or trend >= 0):
        return "Broad Improvement"
    if score >= 55:
        return "Mixed Improvement"
    if score >= 45:
        return "Mixed / Divergent"
    if score >= 35:
        return "Weakening"
    return "Stress"


def classify_regime(row: pd.Series) -> str:
    health = row.get("vn100_health_score", np.nan)
    revenue = row.get("revenue_breadth", np.nan)
    profit = row.get("profit_breadth", np.nan)
    cfo = row.get("cfo_breadth", np.nan)
    healthy = row.get("healthy_growth_breadth", np.nan)
    wc_stress = row.get("working_capital_stress_index", np.nan)
    leverage = row.get("leverage_stress_index", np.nan)

    if health >= 70 and healthy >= 0.50 and cfo >= 0.55:
        return "Strong Expansion"
    if health >= 60 and revenue >= 0.55 and profit >= 0.45 and cfo >= 0.40:
        return "Healthy Recovery"
    if health < 35 or wc_stress >= 70 or leverage >= 70:
        return "Stress"
    if health < 45:
        return "Weakening"
    return "Mixed / Divergent"


def diagnosis_for_row(row: pd.Series) -> list[str]:
    messages: list[str] = []
    if row.get("revenue_breadth", 0) > row.get("cfo_breadth", 0) + 0.15:
        messages.append("Revenue recovery is broader than cashflow recovery")
    if row.get("profit_breadth", 0) > row.get("cfo_breadth", 0) + 0.10:
        messages.append("Earnings quality remains weak")
    if row.get("healthy_growth_breadth", 1) < 0.35:
        messages.append("Healthy growth breadth is narrow")
    if row.get("sector_diffusion_score", 1) < 0.45:
        messages.append("Recovery is concentrated in a limited set of sectors")
    if row.get("working_capital_stress_index", 0) >= 60:
        messages.append("Working capital stress is elevated")
    if row.get("leverage_stress_index", 0) >= 60:
        messages.append("Leverage stress is elevated")
    return messages or ["Corporate health is broadly balanced"]


def compute_sector_scores(company_scores: pd.DataFrame) -> pd.DataFrame:
    agg_cols = [
        "corporate_health_score",
        "growth_score",
        "profitability_score",
        "cash_conversion_score",
        "working_capital_stress_score",
        "leverage_stress_score",
        "balance_sheet_resilience_score",
        "capital_allocation_score",
        "matrix_consistency_score",
    ]
    grouped = company_scores.groupby(["sector", "period", "period_order"], dropna=False)
    sector = grouped[agg_cols].agg(["mean", "median"]).reset_index()
    sector.columns = [
        "_".join([part for part in col if part]).rstrip("_") if isinstance(col, tuple) else col
        for col in sector.columns
    ]
    sector = sector.rename(
        columns={
            "corporate_health_score_mean": "sector_health_score",
            "growth_score_mean": "sector_growth_score",
            "profitability_score_mean": "sector_profitability_score",
            "cash_conversion_score_mean": "sector_cash_conversion_score",
            "working_capital_stress_score_mean": "sector_working_capital_stress",
            "leverage_stress_score_mean": "sector_leverage_stress",
            "balance_sheet_resilience_score_mean": "sector_balance_sheet_score",
            "capital_allocation_score_mean": "sector_capital_allocation_score",
            "matrix_consistency_score_mean": "sector_matrix_consistency_score",
        }
    )
    sector["company_count"] = grouped["ticker"].nunique().to_numpy()
    sector["sector_health_trend_yoy"] = (
        sector.sort_values("period_order")
        .groupby("sector")["sector_health_score"]
        .transform(lambda s: s - s.shift(4))
    )
    sector["sector_diffusion_label"] = sector.apply(
        lambda row: diffusion_label(row["sector_health_score"], row["sector_health_trend_yoy"]),
        axis=1,
    )
    return sector.sort_values(["period_order", "sector"]).reset_index(drop=True)


def compute_sector_diffusion(sector_scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for period, sub in sector_scores.groupby("period"):
        trend = sub["sector_health_trend_yoy"]
        positive = np.where(trend.notna(), trend > 0, sub["sector_health_score"] >= 50)
        valid = sub["sector_health_score"].notna()
        score = float(np.mean(positive[valid])) if valid.any() else np.nan
        rows.append(
            {
                "period": period,
                "period_order": sub["period_order"].iloc[0],
                "sector_diffusion_score": score,
                "positive_sector_count": int(np.sum(positive[valid])) if valid.any() else 0,
                "valid_sector_count": int(valid.sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("period_order").reset_index(drop=True)


def compute_breadth(company_scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for period, sub in company_scores.groupby("period"):
        def breadth(condition, valid):
            valid = valid.fillna(False)
            if valid.sum() == 0:
                return np.nan
            return float(condition[valid].mean())

        revenue_valid = sub["ttm_revenue_yoy"].notna()
        profit_valid = sub["ttm_net_profit_yoy"].notna()
        cfo_valid = sub["ttm_cfo_yoy"].notna()
        margin_valid = sub["ebit_margin_yoy_delta"].notna()
        healthy_condition = (
            (sub["ttm_revenue_yoy"] > 0)
            & (sub["ttm_net_profit_yoy"] > 0)
            & (sub["ttm_cfo"] > 0)
            & (sub["cfo_to_net_profit"] >= 0.8)
            & (sub["working_capital_stress_score"] < 70)
            & (sub["leverage_stress_score"] < 70)
        )
        healthy_valid = (
            sub["ttm_revenue_yoy"].notna()
            & sub["ttm_net_profit_yoy"].notna()
            & sub["ttm_cfo"].notna()
        )
        rows.append(
            {
                "period": period,
                "period_order": sub["period_order"].iloc[0],
                "valid_company_count": int(sub["ticker"].nunique()),
                "revenue_breadth": breadth(sub["ttm_revenue_yoy"] > 0, revenue_valid),
                "profit_breadth": breadth(sub["ttm_net_profit_yoy"] > 0, profit_valid),
                "cfo_breadth": breadth(sub["ttm_cfo_yoy"] > 0, cfo_valid),
                "margin_breadth": breadth(sub["ebit_margin_yoy_delta"] > 0, margin_valid),
                "healthy_growth_breadth": breadth(healthy_condition, healthy_valid),
                "working_capital_stress_index": sub["working_capital_stress_score"].mean(),
                "leverage_stress_index": sub["leverage_stress_score"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("period_order").reset_index(drop=True)


def compute_vn100_scores(
    company_scores: pd.DataFrame,
    sector_scores: pd.DataFrame,
    sector_diffusion: pd.DataFrame,
) -> pd.DataFrame:
    breadth = compute_breadth(company_scores)
    rows = []
    core_cols = [
        "corporate_health_score",
        *CORE_COLUMNS,
        "leverage_stress_score",
        "matrix_consistency_score",
    ]
    for period, sub in company_scores.groupby("period"):
        row = {
            "period": period,
            "period_order": sub["period_order"].iloc[0],
            "vn100_health_score": sub["corporate_health_score"].mean(),
            "vn100_health_score_market_cap_weighted": weighted_average(
                sub["corporate_health_score"], sub["market_cap"]
            ),
        }
        for col in core_cols:
            row[f"equal_weight_{col}"] = sub[col].mean()
            row[f"market_cap_weight_{col}"] = weighted_average(sub[col], sub["market_cap"])
        rows.append(row)

    vn = pd.DataFrame(rows)
    vn = vn.merge(breadth, on=["period", "period_order"], how="left")
    vn = vn.merge(sector_diffusion, on=["period", "period_order"], how="left")
    vn["sector_diffusion_score"] = vn["sector_diffusion_score"].fillna(0.5)
    vn["regime"] = vn.apply(classify_regime, axis=1)
    vn["main_diagnosis"] = vn.apply(lambda row: json.dumps(diagnosis_for_row(row)), axis=1)
    return vn.sort_values("period_order").reset_index(drop=True)


def add_breadth_diffusion_to_companies(
    company_scores: pd.DataFrame,
    sector_scores: pd.DataFrame,
    sector_diffusion: pd.DataFrame,
) -> pd.DataFrame:
    out = company_scores.copy()
    sector_join = sector_scores[[
        "sector",
        "period",
        "sector_health_score",
        "sector_growth_score",
        "sector_cash_conversion_score",
        "sector_working_capital_stress",
        "sector_leverage_stress",
        "sector_diffusion_label",
    ]]
    out = out.merge(sector_join, on=["sector", "period"], how="left")
    out = out.merge(
        sector_diffusion[["period", "sector_diffusion_score"]],
        on="period",
        how="left",
    )
    out["breadth_diffusion_score"] = (
        0.5 * out["sector_health_score"].fillna(50)
        + 0.5 * (out["sector_diffusion_score"].fillna(0.5) * 100)
    )
    return out
