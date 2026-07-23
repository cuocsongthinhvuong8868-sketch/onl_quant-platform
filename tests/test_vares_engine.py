import numpy as np
import pandas as pd
import polars as pl

from tools.va_res.quant.metrics import (
    METHOD_VERSION,
    RiskConfig,
    SystemicRiskEngine,
    summarize_vares_state,
)
from tools.va_res.report import snapshot
from shared.data_loader import load_close_prices


def _price_frame(ticker: str, returns: list[float]) -> pl.DataFrame:
    prices = [100.0]
    for daily_return in returns:
        prices.append(prices[-1] * (1.0 + daily_return))
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pl.DataFrame({"time": dates, ticker: prices})


def test_historical_var_uses_prior_window_only():
    config = RiskConfig(
        window_years=1,
        trading_days=3,
        min_periods=2,
        confidence=0.95,
        ema_smooth_span=0,
        max_abs_return=1.0,
    )
    engine = SystemicRiskEngine(config)
    df_price = _price_frame("AAA", [0.01, 0.01, -0.20, 0.01])

    metrics = engine.calculate_risk_metrics(df_price, method="historical").to_pandas()
    crash_row = metrics.iloc[3]

    assert np.isclose(crash_row["return"], -0.20)
    assert crash_row["VaR"] > 0.0
    assert crash_row["return"] < crash_row["VaR"]


def test_bad_ticks_are_removed_before_risk_estimation():
    config = RiskConfig(
        window_years=1,
        trading_days=3,
        min_periods=2,
        confidence=0.95,
        ema_smooth_span=0,
        max_abs_return=0.50,
    )
    engine = SystemicRiskEngine(config)
    df_price = pl.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=5, freq="D"),
            "AAA": [100.0, 101.0, 0.0, 102.0, 103.0],
        }
    )

    metrics = engine.calculate_risk_metrics(df_price, method="historical").to_pandas()

    assert np.isnan(metrics.loc[2, "return"])
    assert np.isnan(metrics.loc[3, "return"])


def test_contagion_index_uses_valid_denominator():
    engine = SystemicRiskEngine()
    df_metrics = pl.DataFrame(
        {
            "time": [pd.Timestamp("2024-01-05")] * 3,
            "ticker": ["AAA", "BBB", "CCC"],
            "price": [10.0, 20.0, 30.0],
            "return": [-0.06, -0.01, None],
            "VaR": [-0.05, -0.04, -0.03],
            "ES": [-0.08, -0.07, -0.06],
            "Spread_Raw": [0.03, 0.03, 0.03],
            "Spread": [0.03, 0.03, 0.03],
        }
    )

    contagion = engine.calculate_contagion_index(df_metrics).to_dicts()[0]

    assert contagion["Breached_Count"] == 1
    assert contagion["Valid_Names"] == 2
    assert contagion["Total_Names"] == 3
    assert contagion["Contagion_Index"] == 50.0


def test_complacency_excludes_vnindex_benchmark_from_signals():
    config = RiskConfig(
        window_years=1,
        trading_days=3,
        min_periods=2,
        confidence=0.95,
        trend_ma_window=2,
        pr_window=2,
    )
    engine = SystemicRiskEngine(config)
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    rows = []
    for ticker, base_price in [("VNINDEX", 1000.0), ("AAA", 10.0), ("BBB", 20.0)]:
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "time": date,
                    "ticker": ticker,
                    "price": base_price + idx,
                    "return": 0.01,
                    "VaR": -0.03,
                    "ES": -0.05,
                    "Spread_Raw": 0.02,
                    "Spread": 0.02,
                }
            )
    df_metrics = pl.DataFrame(rows).sort(["time", "ticker"])

    complacency = engine.calculate_complacency_index(df_metrics, benchmark_ticker="VNINDEX")
    aggregate = engine.calculate_complacency_aggregate(complacency).to_pandas().iloc[-1]

    assert "VNINDEX" not in set(complacency["ticker"].unique().to_list())
    assert aggregate["Total_Names"] == 2


def test_vares_summary_flags_threshold_as_active():
    summary = summarize_vares_state(
        stress_index_pct=40.0,
        complacency_index_pct=3.7,
        breached_count=12,
        valid_vn30_count=30,
        mispriced_count=4,
        valid_market_count=107,
    )

    assert summary["methodology_version"] == METHOD_VERSION
    assert summary["vares_regime"] == "CONTAGION_ACTIVE"
    assert summary["stress_level"] == "ACTIVE"


def test_vares_report_snapshot_exposes_v2_fields():
    snap = snapshot(load_close_prices())

    assert snap["methodology_version"] == METHOD_VERSION
    assert snap["vares_regime"] in {
        "CONTAGION_ACTIVE",
        "COMPLACENCY_DANGER",
        "LATENT_TAIL_RISK",
        "NO_VARES_STRESS",
    }
    assert snap["valid_vn30_count"] >= snap["breached_count"]
    assert snap["valid_market_count"] >= snap["mispriced_count"]
