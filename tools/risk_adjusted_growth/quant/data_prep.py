import logging

import pandas as pd

logger = logging.getLogger(__name__)

# market_data.csv lưu giá theo nghìn VND (convention vnstock cho VN stocks):
# VCB = 61.5 ↔ 61,500 VND. Còn BVPS trong bank_fundamentals.csv ở đơn vị VND
# đầy đủ (VCB BVPS ~ 27,231). Để P/B đồng nhất đơn vị: price * 1000 / bvps.
PRICE_THOUSANDS_TO_VND = 1000

# Cap cash payout 50% để tránh outlier (special dividend) làm méo ROE retention.
# Có thể nâng nếu khẩu vị ngân hàng có chính sách chia cao bền vững.
CASH_PAYOUT_CAP = 0.5

# Threshold cảnh báo BVPS rõ ràng sai unit. BVPS bank thấp nhất trong dataset
# VN ~10k VND. Dưới mức này nghi đơn vị nghìn VND hoặc lỗi parse.
BVPS_UNIT_SANITY_FLOOR = 1000


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
    return min(float(s.mean()) / 100.0, CASH_PAYOUT_CAP)


def build_base_table(df_fund: pd.DataFrame, df_div: pd.DataFrame, price_row: pd.Series) -> pd.DataFrame:
    rows = []
    suspect_unit_tickers = []
    for _, r in df_fund.iterrows():
        ticker = str(r["ticker"]).upper()
        roe_geomean = float(r["Geomean ROE"])
        roe_stdev = float(r["Stdev ROE"])
        bvps = float(r["BVPS"])
        price = float(price_row.get(ticker, 0.0)) if price_row is not None else 0.0

        if 0 < bvps < BVPS_UNIT_SANITY_FLOOR:
            suspect_unit_tickers.append((ticker, bvps))

        pb = (price * PRICE_THOUSANDS_TO_VND / bvps) if (bvps > 0 and price > 0) else 0.0
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

    if suspect_unit_tickers:
        logger.warning(
            "BVPS có vẻ sai unit (<%d VND) cho: %s. P/B sẽ bị inflate. "
            "Kiểm tra lại file bank_fundamentals.csv — kỳ vọng BVPS theo VND đầy đủ.",
            BVPS_UNIT_SANITY_FLOOR,
            ", ".join(f"{t}={v}" for t, v in suspect_unit_tickers),
        )

    return pd.DataFrame(rows)
