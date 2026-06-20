from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from .config import CORE_COLUMNS, CORE_PAIR_EXPECTATIONS, DEFAULT_ROLLING_WINDOW


def corr_to_score(correlation: float, expected_direction: int) -> float:
    if pd.isna(correlation):
        return np.nan
    aligned = correlation * expected_direction
    return float(np.clip((aligned + 1) / 2 * 100, 0, 100))


def severity_from_score(score: float) -> str:
    if pd.isna(score):
        return "Insufficient Data"
    if score >= 70:
        return "Low"
    if score >= 45:
        return "Medium"
    return "High"


def diagnostic_label(left: str, right: str, correlation: float, expected_direction: int) -> str:
    if pd.isna(correlation):
        return "Insufficient Data"
    aligned = correlation * expected_direction
    pair = {left, right}
    if aligned >= 0.4:
        return "Confirmed"
    if "cash_conversion_score" in pair and "profitability_score" in pair:
        return "Earnings Quality Divergence"
    if "growth_score" in pair and "working_capital_stress_score" in pair:
        return "Working Capital Absorption"
    if "balance_sheet_resilience_score" in pair:
        return "Balance Sheet Drag"
    return "Divergence"


def compute_core_consistency_matrix(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    available = [column for column in CORE_COLUMNS if column in scored]
    for period, sub in scored.groupby("period"):
        matrix = sub[available].corr(min_periods=5)
        for left, right in itertools.product(available, available):
            corr = matrix.loc[left, right] if left in matrix.index and right in matrix.columns else np.nan
            if left == right:
                expected = 1
            else:
                expected = CORE_PAIR_EXPECTATIONS.get((left, right), CORE_PAIR_EXPECTATIONS.get((right, left), 1))
            score = corr_to_score(corr, expected)
            rows.append(
                {
                    "period": period,
                    "period_order": sub["period_order"].iloc[0],
                    "left_core": left,
                    "right_core": right,
                    "correlation": corr,
                    "expected_direction": expected,
                    "consistency_score": score,
                    "diagnostic_label": diagnostic_label(left, right, corr, expected),
                    "severity": severity_from_score(score),
                }
            )
    return pd.DataFrame(rows).sort_values(["period_order", "left_core", "right_core"]).reset_index(drop=True)


def compute_company_rolling_consistency(
    scored: pd.DataFrame, window: int = DEFAULT_ROLLING_WINDOW
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    summary_rows: list[dict] = []
    available = [column for column in CORE_COLUMNS if column in scored]

    for ticker, sub in scored.sort_values("period_order").groupby("ticker"):
        sub = sub.reset_index(drop=True)
        for row_idx, row in sub.iterrows():
            window_df = sub.iloc[max(0, row_idx - window + 1) : row_idx + 1]
            period_scores = []
            for (left, right), expected in CORE_PAIR_EXPECTATIONS.items():
                if left not in available or right not in available:
                    continue
                corr = np.nan
                valid = window_df[[left, right]].dropna()
                if len(valid) >= 6 and valid[left].nunique() > 1 and valid[right].nunique() > 1:
                    corr = valid[left].corr(valid[right])
                score = corr_to_score(corr, expected)
                period_scores.append(score)
                rows.append(
                    {
                        "ticker": ticker,
                        "period": row["period"],
                        "period_order": row["period_order"],
                        "left_core": left,
                        "right_core": right,
                        "correlation": corr,
                        "expected_direction": expected,
                        "consistency_score": score,
                        "diagnostic_label": diagnostic_label(left, right, corr, expected),
                        "severity": severity_from_score(score),
                    }
                )
            summary_rows.append(
                {
                    "ticker": ticker,
                    "period": row["period"],
                    "period_order": row["period_order"],
                    "rolling_consistency_score": np.nanmean(period_scores)
                    if np.isfinite(period_scores).any()
                    else np.nan,
                }
            )

    detail = pd.DataFrame(rows)
    summary = pd.DataFrame(summary_rows)
    return detail, summary


def _status(score: float) -> str:
    if pd.isna(score):
        return "insufficient"
    if score >= 75:
        return "confirmed"
    if score >= 45:
        return "weak"
    return "broken"


def _rule_score(condition: bool | np.bool_, weak_condition: bool | np.bool_ = False, missing: bool = False) -> float:
    if missing:
        return np.nan
    if bool(condition):
        return 100.0
    if bool(weak_condition):
        return 55.0
    return 20.0


def compute_transmission_matrix(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []

    for _, row in scored.iterrows():
        values = row.to_dict()

        def is_missing(*keys: str) -> bool:
            return any(pd.isna(values.get(key)) for key in keys)

        checks = [
            (
                "Revenue -> Gross Profit",
                _rule_score(
                    values.get("ttm_revenue_yoy", np.nan) > 0
                    and values.get("ttm_gross_profit_yoy", np.nan) > 0
                    and values.get("gross_margin_yoy_delta", np.nan) >= -0.005,
                    values.get("ttm_revenue_yoy", np.nan) > 0
                    and values.get("ttm_gross_profit_yoy", np.nan) > -0.05,
                    is_missing("ttm_revenue_yoy", "ttm_gross_profit_yoy", "gross_margin_yoy_delta"),
                ),
                "Revenue quality",
            ),
            (
                "Gross Profit -> EBIT",
                _rule_score(
                    values.get("ttm_gross_profit_yoy", np.nan) > 0
                    and values.get("ttm_ebit_yoy", np.nan) > 0
                    and values.get("ebit_margin_yoy_delta", np.nan) >= -0.005,
                    values.get("ttm_gross_profit_yoy", np.nan) > 0
                    and values.get("ttm_ebit_yoy", np.nan) > -0.05,
                    is_missing("ttm_gross_profit_yoy", "ttm_ebit_yoy", "ebit_margin_yoy_delta"),
                ),
                "Operating cost control",
            ),
            (
                "EBIT -> LNST",
                _rule_score(
                    values.get("ttm_ebit_yoy", np.nan) > 0
                    and values.get("ttm_net_profit_yoy", np.nan) > 0,
                    values.get("ttm_ebit_yoy", np.nan) > -0.05
                    and values.get("ttm_net_profit_yoy", np.nan) > -0.05,
                    is_missing("ttm_ebit_yoy", "ttm_net_profit_yoy"),
                ),
                "Financing and tax drag",
            ),
            (
                "LNST -> CFO",
                _rule_score(
                    values.get("ttm_net_profit_yoy", np.nan) > 0
                    and values.get("ttm_cfo", np.nan) > 0
                    and values.get("cfo_to_net_profit", np.nan) >= 0.8,
                    values.get("ttm_cfo", np.nan) > 0,
                    is_missing("ttm_net_profit_yoy", "ttm_cfo", "cfo_to_net_profit"),
                ),
                "Earnings quality",
            ),
            (
                "CFO -> FCF",
                _rule_score(
                    values.get("ttm_cfo", np.nan) > 0
                    and values.get("ttm_fcf", np.nan) >= -0.25 * abs(values.get("ttm_cfo", np.nan)),
                    values.get("ttm_cfo", np.nan) > 0,
                    is_missing("ttm_cfo", "ttm_fcf"),
                ),
                "Cash after investment",
            ),
            (
                "FCF -> Equity / Balance Sheet",
                _rule_score(
                    (
                        values.get("ttm_fcf", np.nan) > 0
                        or values.get("equity_yoy", np.nan) > 0
                    )
                    and values.get("leverage_stress_score", np.nan) < 70,
                    values.get("equity_yoy", np.nan) > -0.05,
                    is_missing("ttm_fcf", "equity_yoy", "leverage_stress_score"),
                ),
                "Self-funded growth",
            ),
        ]

        for link, score, meaning in checks:
            rows.append(
                {
                    "ticker": values["ticker"],
                    "period": values["period"],
                    "period_order": values["period_order"],
                    "sector": values.get("sector"),
                    "link": link,
                    "meaning": meaning,
                    "score": score,
                    "status": _status(score),
                    "severity": severity_from_score(score),
                }
            )

    detail = pd.DataFrame(rows)
    summary = (
        detail.groupby(["ticker", "period", "period_order"], as_index=False)["score"]
        .mean()
        .rename(columns={"score": "transmission_score"})
    )
    return detail, summary


def compute_matrix_consistency_score(
    rolling_summary: pd.DataFrame, transmission_summary: pd.DataFrame
) -> pd.DataFrame:
    summary = transmission_summary.merge(
        rolling_summary,
        on=["ticker", "period", "period_order"],
        how="left",
    )
    summary["matrix_consistency_score"] = summary[[
        "transmission_score",
        "rolling_consistency_score",
    ]].mean(axis=1, skipna=True)
    summary["matrix_consistency_score"] = summary["matrix_consistency_score"].fillna(50).clip(0, 100)
    return summary


def compute_pca_factor(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregate = (
        scored.groupby(["period", "period_order"], as_index=False)[CORE_COLUMNS]
        .mean(numeric_only=True)
        .sort_values("period_order")
    )
    core_matrix = aggregate[CORE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    core_matrix = core_matrix.interpolate(limit_direction="both").fillna(50)
    if len(core_matrix) < 4:
        aggregate["common_health_factor"] = np.nan
        aggregate["explained_variance_ratio"] = np.nan
        return aggregate[["period", "period_order", "common_health_factor", "explained_variance_ratio"]], pd.DataFrame()

    x = core_matrix.to_numpy(dtype=float)
    x = (x - x.mean(axis=0)) / np.where(x.std(axis=0) == 0, 1, x.std(axis=0))
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    pc1 = x @ vt[0]
    if pc1[-1] < pc1[0]:
        pc1 = -pc1
        vt[0] = -vt[0]
    explained = (s[0] ** 2) / np.sum(s**2) if np.sum(s**2) else np.nan
    factor = aggregate[["period", "period_order"]].copy()
    factor["common_health_factor"] = pc1
    factor["explained_variance_ratio"] = explained
    loadings = pd.DataFrame(
        {
            "core": CORE_COLUMNS,
            "pc1_loading": vt[0],
            "explained_variance_ratio": explained,
        }
    )
    return factor, loadings
