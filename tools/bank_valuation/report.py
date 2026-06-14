from __future__ import annotations

from shared.data_loader import load_close_prices, load_volumes
from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime
from tools.bank_valuation.quant.pipeline import bank_valuation_source_signature, run_bank_valuation_pipeline


def snapshot(df_close=None, load_custom=None) -> dict:
    close_prices = df_close if df_close is not None else load_close_prices()
    try:
        volumes = load_volumes()
    except Exception:
        volumes = None

    valuation_df, _ = run_bank_valuation_pipeline(close_prices=close_prices, volumes=volumes)
    regime = calculate_bank_valuation_regime(valuation_df)
    price_date = close_prices.index.max().strftime("%Y-%m-%d") if not close_prices.empty else ""

    if valuation_df.empty:
        return {
            "status": "empty",
            "price_date": price_date,
            "source_signature": bank_valuation_source_signature(),
            "bank_count": 0,
            "regime": "N/A",
            "error": "No valuation rows",
        }

    best = valuation_df.sort_values("valuation_gap_pct", ascending=False).iloc[0]
    worst = valuation_df.sort_values("valuation_gap_pct", ascending=True).iloc[0]
    return {
        "status": "ok",
        "price_date": price_date,
        "source_signature": bank_valuation_source_signature(),
        "bank_count": int(len(valuation_df)),
        "eligible_banks": int(regime.eligible_banks),
        "regime": regime.regime_label,
        "breadth_score": round(float(regime.bank_valuation_breadth_score), 6),
        "median_valuation_gap": round(float(regime.median_valuation_gap), 6),
        "best_ticker": str(best["ticker"]),
        "best_valuation_gap": round(float(best["valuation_gap_pct"]), 6),
        "worst_ticker": str(worst["ticker"]),
        "worst_valuation_gap": round(float(worst["valuation_gap_pct"]), 6),
        "error": "",
    }
