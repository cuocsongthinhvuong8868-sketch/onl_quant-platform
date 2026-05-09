import pandas as pd
from tools.risk_adjusted_growth.quant.data_prep import build_base_table
from tools.risk_adjusted_growth.quant.scoring import compute_scores


def _normalize_fund(df_fund: pd.DataFrame) -> pd.DataFrame:
    if "ticker" in df_fund.columns:
        return df_fund
    if df_fund.index.name and str(df_fund.index.name).lower() == "ticker":
        return df_fund.reset_index()
    if "Unnamed: 0" in df_fund.columns:
        return df_fund.rename(columns={"Unnamed: 0": "ticker"})
    return df_fund.reset_index().rename(columns={"index": "ticker"})


def snapshot(df_close, load_custom):
    df_fund = _normalize_fund(load_custom("bank_fundamentals.csv"))
    try:
        df_div = load_custom("dividend_cache.csv")
    except FileNotFoundError:
        df_div = pd.DataFrame()

    if "ticker" not in df_fund.columns:
        raise ValueError("bank_fundamentals.csv thiếu cột ticker")

    latest_prices = df_close.ffill().iloc[-1]
    base = build_base_table(df_fund, df_div, latest_prices)
    scored = compute_scores(base, k_value=1.0, coe_decimal=0.14, bvps_change_pct=0.0, pb_penalty_pct=0.0)
    top = scored.iloc[0]
    return {
        "snapshot_date": df_close.index[-1].strftime("%Y-%m-%d"),
        "top_bank": str(top["Ngân hàng"]),
        "top_alpha": round(float(top["Economic Alpha"]), 6),
        "median_alpha": round(float(scored["Economic Alpha"].median()), 6),
        "positive_alpha_count": int((scored["Economic Alpha"] > 0).sum()),
        "bank_count": int(len(scored)),
    }
