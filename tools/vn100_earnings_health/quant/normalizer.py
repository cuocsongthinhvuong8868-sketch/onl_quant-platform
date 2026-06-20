import numpy as np
import pandas as pd


FLOW_METRICS = [
    "revenue",
    "cost_of_sales",
    "gross_profit",
    "ebit",
    "net_profit",
    "interest_expense",
    "cfo",
    "capex",
    "depreciation",
    "investing_cashflow",
    "financing_cashflow",
]

BALANCE_METRICS = [
    "cash",
    "current_assets",
    "total_assets",
    "receivables",
    "inventory",
    "payables",
    "short_term_debt",
    "long_term_debt",
    "total_debt",
    "net_debt",
    "liabilities",
    "current_liabilities",
    "equity",
    "fixed_assets",
]


def safe_divide(numerator, denominator):
    denom = denominator.replace(0, np.nan) if isinstance(denominator, pd.Series) else denominator
    with np.errstate(divide="ignore", invalid="ignore"):
        return numerator / denom


def growth_rate(series: pd.Series, periods: int) -> pd.Series:
    previous = series.shift(periods)
    denominator = previous.abs()
    denominator = denominator.where(denominator > 1e-9)
    return (series - previous) / denominator


def add_ttm_and_growth(canonical: pd.DataFrame) -> pd.DataFrame:
    df = canonical.copy()
    df = df.sort_values(["ticker", "period_order"]).reset_index(drop=True)
    group = df.groupby("ticker", group_keys=False)

    for metric in FLOW_METRICS:
        if metric in df:
            df[f"ttm_{metric}"] = group[metric].transform(
                lambda s: s.rolling(4, min_periods=4).sum()
            )
            df[f"{metric}_qoq"] = group[metric].transform(lambda s: growth_rate(s, 1))
            df[f"{metric}_yoy"] = group[metric].transform(lambda s: growth_rate(s, 4))
            df[f"ttm_{metric}_yoy"] = group[f"ttm_{metric}"].transform(
                lambda s: growth_rate(s, 4)
            )

    for metric in BALANCE_METRICS:
        if metric in df:
            df[f"{metric}_qoq"] = group[metric].transform(lambda s: growth_rate(s, 1))
            df[f"{metric}_yoy"] = group[metric].transform(lambda s: growth_rate(s, 4))

    df["fcf"] = df["cfo"] - df["capex"].abs()
    df["ttm_fcf"] = df["ttm_cfo"] - df["ttm_capex"].abs()
    df["fcf_yoy"] = group["fcf"].transform(lambda s: growth_rate(s, 4))
    df["ttm_fcf_yoy"] = group["ttm_fcf"].transform(lambda s: growth_rate(s, 4))

    avg_assets = (df["total_assets"] + group["total_assets"].shift(4)) / 2
    avg_equity = (df["equity"] + group["equity"].shift(4)) / 2

    df["gross_margin"] = safe_divide(df["ttm_gross_profit"], df["ttm_revenue"])
    df["ebit_margin"] = safe_divide(df["ttm_ebit"], df["ttm_revenue"])
    df["net_margin"] = safe_divide(df["ttm_net_profit"], df["ttm_revenue"])
    df["cfo_margin"] = safe_divide(df["ttm_cfo"], df["ttm_revenue"])
    df["fcf_margin"] = safe_divide(df["ttm_fcf"], df["ttm_revenue"])
    df["roa"] = safe_divide(df["ttm_net_profit"], avg_assets)
    df["roe"] = safe_divide(df["ttm_net_profit"], avg_equity)

    df["cfo_to_net_profit"] = safe_divide(df["ttm_cfo"], df["ttm_net_profit"])
    df["fcf_to_net_profit"] = safe_divide(df["ttm_fcf"], df["ttm_net_profit"])
    df["accrual_ratio"] = safe_divide(df["ttm_net_profit"] - df["ttm_cfo"], df["total_assets"])

    df["receivables_to_revenue"] = safe_divide(df["receivables"], df["ttm_revenue"])
    df["inventory_to_revenue"] = safe_divide(df["inventory"], df["ttm_revenue"])
    df["payables_to_cogs"] = safe_divide(df["payables"], df["ttm_cost_of_sales"].abs())
    df["receivables_growth_spread"] = df["receivables_yoy"] - df["ttm_revenue_yoy"]
    df["inventory_growth_spread"] = df["inventory_yoy"] - df["ttm_revenue_yoy"]

    df["debt_to_equity"] = safe_divide(df["total_debt"], df["equity"])
    df["liabilities_to_assets"] = safe_divide(df["liabilities"], df["total_assets"])
    df["equity_to_assets"] = safe_divide(df["equity"], df["total_assets"])
    ebitda = df["ttm_ebit"] + df["ttm_depreciation"].fillna(0)
    df["net_debt_to_ebitda"] = safe_divide(df["net_debt"], ebitda)
    df["interest_coverage"] = safe_divide(df["ttm_ebit"], df["ttm_interest_expense"].abs())
    df["cash_to_short_term_debt"] = safe_divide(df["cash"], df["short_term_debt"])
    df["current_ratio"] = safe_divide(df["current_assets"], df["current_liabilities"])
    df["quick_ratio"] = safe_divide(df["current_assets"] - df["inventory"].fillna(0), df["current_liabilities"])
    df["debt_growth_spread"] = df["total_debt_yoy"] - df["ttm_revenue_yoy"]
    df["interest_growth_spread"] = df["ttm_interest_expense_yoy"] - df["ttm_ebit_yoy"]

    df["capex_to_revenue"] = safe_divide(df["ttm_capex"].abs(), df["ttm_revenue"])
    df["capex_to_depreciation"] = safe_divide(df["ttm_capex"].abs(), df["ttm_depreciation"].abs())
    df["asset_growth"] = df["total_assets_yoy"]
    df["fixed_asset_growth"] = df["fixed_assets_yoy"]

    for metric in ["gross_margin", "ebit_margin", "net_margin", "cfo_margin", "fcf_margin"]:
        df[f"{metric}_yoy_delta"] = group[metric].transform(lambda s: s - s.shift(4))

    df["valid_for_yoy_view"] = df["year"] <= 2025
    df["valid_for_qoq_view"] = True
    return df
