import pandas as pd


def average_cash_payout(symbol: str, df_div: pd.DataFrame) -> float:
    if df_div is None or df_div.empty:
        return 0.0
    symbol_col = "Ma CP" if "Ma CP" in df_div.columns else "ticker"
    payout_col = "Ty le tien (%)" if "Ty le tien (%)" in df_div.columns else "cash_payout_pct"
    if symbol_col not in df_div.columns or payout_col not in df_div.columns:
        return 0.0

    s = pd.to_numeric(
        df_div.loc[df_div[symbol_col].astype(str).str.upper() == symbol.upper(), payout_col],
        errors="coerce",
    ).dropna()
    if s.empty:
        return 0.0
    return min(float(s.mean()) / 100.0, 0.5)


def build_base_table(df_fund: pd.DataFrame, df_div: pd.DataFrame, price_row: pd.Series) -> pd.DataFrame:
    rows = []
    for _, r in df_fund.iterrows():
        ticker = str(r["ticker"]).upper()
        roe_geomean = float(r["Geomean ROE"])
        roe_stdev = float(r["Stdev ROE"])
        bvps = float(r["BVPS"])
        price = float(price_row.get(ticker, 0.0)) if price_row is not None else 0.0

        pb = (price / bvps) if (bvps > 0 and price > 0) else 0.0
        cash_payout = average_cash_payout(ticker, df_div)

        rows.append(
            {
                "Ngân hàng": ticker,
                "Geomean ROE": roe_geomean,
                "Stdev ROE": roe_stdev,
                "Cash Payout Ratio": cash_payout,
                "P/B Gốc": pb,
            }
        )

    return pd.DataFrame(rows)
