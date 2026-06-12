from tools.risk_adjusted_growth.quant.data_prep import (
    build_base_table_from_statistics,
    risk_adjusted_growth_source_signature,
)
from tools.risk_adjusted_growth.quant.scoring import compute_scores


def snapshot(df_close, load_custom):
    latest_prices = df_close.ffill().iloc[-1]
    base = build_base_table_from_statistics(price_row=latest_prices)
    snapshot_date = df_close.index[-1].strftime("%Y-%m-%d")
    source_date = risk_adjusted_growth_source_signature().split(":", 1)[0]

    scored = compute_scores(base, k_value=1.0, coe_decimal=0.14, bvps_change_pct=0.0, pb_penalty_pct=0.0)
    top = scored.iloc[0]
    ticker_col = "Ticker" if "Ticker" in scored.columns else "Ngân hàng"
    return {
        "snapshot_date": snapshot_date,
        "top_bank": str(top[ticker_col]),
        "top_ticker": str(top[ticker_col]),
        "statistics_source_date": source_date,
        "top_alpha": round(float(top["Economic Alpha"]), 6),
        "median_alpha": round(float(scored["Economic Alpha"].median()), 6),
        "positive_alpha_count": int((scored["Economic Alpha"] > 0).sum()),
        "ticker_count": int(len(scored)),
        "bank_count": int(len(scored)),
    }
