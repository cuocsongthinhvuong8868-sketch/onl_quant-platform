from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_WINSOR_LOWER,
    DEFAULT_WINSOR_UPPER,
    HIGH_STRESS_THRESHOLD,
    MIN_SECTOR_OBS,
)


def _score_values(values: pd.Series, higher_value_higher_score: bool) -> pd.Series:
    valid = values.dropna()
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if len(valid) == 0:
        return result
    if len(valid) == 1 or valid.nunique(dropna=True) <= 1:
        result.loc[valid.index] = 50.0
        return result

    ranks = valid.rank(method="average", ascending=True)
    pct = (ranks - 1) / (len(valid) - 1) * 100
    if not higher_value_higher_score:
        pct = 100 - pct
    result.loc[valid.index] = pct.clip(0, 100)
    return result


def _winsorized_by_period(df: pd.DataFrame, column: str) -> pd.Series:
    values = df[column].replace([np.inf, -np.inf], np.nan).copy()
    clipped = values.copy()
    for _, idx in df.groupby("period").groups.items():
        sub = values.loc[idx].dropna()
        if len(sub) < 5:
            continue
        lower = sub.quantile(DEFAULT_WINSOR_LOWER)
        upper = sub.quantile(DEFAULT_WINSOR_UPPER)
        clipped.loc[idx] = values.loc[idx].clip(lower, upper)
    return clipped


def percentile_score(
    df: pd.DataFrame,
    column: str,
    *,
    higher_value_higher_score: bool = True,
    sector_relative: bool = True,
) -> pd.Series:
    if column not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)

    work = df[["period", "sector", column]].copy()
    work[column] = _winsorized_by_period(work, column)
    result = pd.Series(np.nan, index=df.index, dtype=float)

    for period, period_idx in work.groupby("period").groups.items():
        period_values = work.loc[period_idx, column]
        global_scores = _score_values(period_values, higher_value_higher_score)
        result.loc[period_idx] = global_scores

        if not sector_relative:
            continue

        period_work = work.loc[period_idx]
        for _, sector_idx in period_work.groupby("sector").groups.items():
            absolute_idx = period_work.loc[sector_idx].index
            if period_work.loc[sector_idx, column].notna().sum() < MIN_SECTOR_OBS:
                continue
            result.loc[absolute_idx] = _score_values(
                work.loc[absolute_idx, column], higher_value_higher_score
            )
    return result.clip(0, 100)


def average_available(df: pd.DataFrame, columns: list[str], neutral: float | None = None) -> pd.Series:
    available = [column for column in columns if column in df]
    if not available:
        return pd.Series(neutral, index=df.index, dtype=float)
    result = df[available].mean(axis=1, skipna=True)
    if neutral is not None:
        result = result.fillna(neutral)
    return result


def add_core_scores(metrics: pd.DataFrame) -> pd.DataFrame:
    df = metrics.copy()

    growth_inputs = {
        "ttm_revenue_yoy": True,
        "ttm_gross_profit_yoy": True,
        "ttm_ebit_yoy": True,
        "ttm_net_profit_yoy": True,
        "revenue_yoy": True,
        "net_profit_yoy": True,
    }
    profitability_inputs = {
        "gross_margin": True,
        "ebit_margin": True,
        "net_margin": True,
        "roa": True,
        "roe": True,
    }
    cash_inputs = {
        "cfo_to_net_profit": True,
        "fcf_to_net_profit": True,
        "cfo_margin": True,
        "fcf_margin": True,
        "accrual_ratio": False,
    }
    wc_stress_inputs = {
        "receivables_growth_spread": True,
        "inventory_growth_spread": True,
        "receivables_to_revenue": True,
        "inventory_to_revenue": True,
    }
    balance_inputs = {
        "debt_to_equity": False,
        "net_debt_to_ebitda": False,
        "liabilities_to_assets": False,
        "interest_coverage": True,
        "cash_to_short_term_debt": True,
        "current_ratio": True,
        "quick_ratio": True,
        "equity_yoy": True,
        "equity_to_assets": True,
    }
    leverage_stress_inputs = {
        "debt_to_equity": True,
        "net_debt_to_ebitda": True,
        "liabilities_to_assets": True,
        "debt_growth_spread": True,
        "interest_growth_spread": True,
        "interest_coverage": False,
    }
    capital_inputs = {
        "fcf_margin": True,
        "asset_growth": True,
        "fixed_asset_growth": True,
        "capex_to_revenue": False,
        "capex_to_depreciation": False,
    }

    def add_metric_scores(prefix: str, inputs: dict[str, bool], stress: bool = False) -> list[str]:
        score_cols = []
        for metric, higher_good in inputs.items():
            score_col = f"{prefix}_{metric}_score"
            if stress:
                df[score_col] = percentile_score(
                    df, metric, higher_value_higher_score=higher_good
                )
            else:
                df[score_col] = percentile_score(
                    df, metric, higher_value_higher_score=higher_good
                )
            score_cols.append(score_col)
        return score_cols

    growth_cols = add_metric_scores("growth", growth_inputs)
    profitability_cols = add_metric_scores("profitability", profitability_inputs)
    cash_cols = add_metric_scores("cash", cash_inputs)
    wc_cols = add_metric_scores("wc_stress", wc_stress_inputs, stress=True)
    balance_cols = add_metric_scores("balance", balance_inputs)
    leverage_cols = add_metric_scores("leverage_stress", leverage_stress_inputs, stress=True)
    capital_cols = add_metric_scores("capital", capital_inputs)

    df["growth_score"] = average_available(df, growth_cols, neutral=50)
    df["profitability_score"] = average_available(df, profitability_cols, neutral=50)
    df["cash_conversion_score"] = average_available(df, cash_cols, neutral=50)
    df["working_capital_stress_score"] = average_available(df, wc_cols, neutral=50)
    df["balance_sheet_resilience_score"] = average_available(df, balance_cols, neutral=50)
    df["leverage_stress_score"] = average_available(df, leverage_cols, neutral=50)
    df["capital_allocation_score"] = average_available(df, capital_cols, neutral=50)

    financial_mask = df["sector"].isin({"Banks", "Financial Services", "Insurance"})
    df.loc[financial_mask & df["working_capital_stress_score"].isna(), "working_capital_stress_score"] = 50

    df["preliminary_health_score"] = composite_health_score(
        df,
        matrix_col=None,
        breadth_col=None,
    )
    return df


def composite_health_score(
    df: pd.DataFrame,
    *,
    matrix_col: str | None = "matrix_consistency_score",
    breadth_col: str | None = "breadth_diffusion_score",
) -> pd.Series:
    matrix = df[matrix_col] if matrix_col and matrix_col in df else 50
    breadth = df[breadth_col] if breadth_col and breadth_col in df else 50

    base = (
        0.25 * df["growth_score"].fillna(50)
        + 0.20 * df["profitability_score"].fillna(50)
        + 0.20 * df["cash_conversion_score"].fillna(50)
        + 0.15 * df["balance_sheet_resilience_score"].fillna(50)
        + 0.10 * df["capital_allocation_score"].fillna(50)
        + 0.05 * pd.Series(breadth, index=df.index).fillna(50)
        + 0.05 * pd.Series(matrix, index=df.index).fillna(50)
    )
    stress_penalty = (
        0.15 * (df["working_capital_stress_score"].fillna(50) - 50)
        + 0.15 * (df["leverage_stress_score"].fillna(50) - 50)
    )
    return (base - stress_penalty).clip(0, 100)


def add_sector_relative_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sector_health_percentile"] = percentile_score(
        out,
        "corporate_health_score",
        higher_value_higher_score=True,
        sector_relative=True,
    )
    out["historical_health_zscore"] = (
        out.groupby("ticker")["corporate_health_score"]
        .transform(lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) else np.nan)
    )
    out["stress_flag"] = (
        (out["working_capital_stress_score"] >= HIGH_STRESS_THRESHOLD)
        | (out["leverage_stress_score"] >= HIGH_STRESS_THRESHOLD)
    )
    return out
