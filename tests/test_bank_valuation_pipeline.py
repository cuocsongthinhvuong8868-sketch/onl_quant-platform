import pandas as pd

from tools.bank_valuation.quant.pipeline import wide_market_data_to_ohlcv


def test_wide_market_data_to_ohlcv_filters_tickers_and_converts_prices():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    close = pd.DataFrame(
        {
            "ACB": [20.5, 21.0],
            "VCB": [60.0, None],
        },
        index=dates,
    )
    volume = pd.DataFrame(
        {
            "ACB": [1000, 2000],
            "VCB": [3000, 4000],
        },
        index=dates,
    )

    out = wide_market_data_to_ohlcv(close, volumes=volume, tickers=["ACB"])

    assert list(out["ticker"].unique()) == ["ACB"]
    assert list(out["close"]) == [20500.0, 21000.0]
    assert list(out["open"]) == [20500.0, 21000.0]
    assert list(out["high"]) == [20500.0, 21000.0]
    assert list(out["low"]) == [20500.0, 21000.0]
    assert list(out["volume"]) == [1000, 2000]
