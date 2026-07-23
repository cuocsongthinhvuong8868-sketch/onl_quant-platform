from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from tools.fear_greed.quant.scoring import METHOD_VERSION, calculate_risk_score


def _metrics_frame(rows: int = 40, mode: str = "greed") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="B")
    rising = np.linspace(0.1, 1.0, rows)
    falling = np.linspace(1.0, 0.1, rows)

    if mode == "panic":
        skewness = np.full(rows, -1.0)
        downside_corr = rising
        upside_corr = falling
        csv_index = rising
    else:
        skewness = np.full(rows, 1.0)
        downside_corr = falling
        upside_corr = rising
        csv_index = falling

    return pd.DataFrame(
        {
            "Market_Factor": np.linspace(-0.01, 0.01, rows),
            "EGARCH_Vol": rising,
            "Skewness": skewness,
            "Downside_Corr": downside_corr,
            "Upside_Corr": upside_corr,
            "CSV_Index": csv_index,
        },
        index=index,
    )


def test_fear_greed_v2_does_not_backfill_early_scores() -> None:
    scored = calculate_risk_score(_metrics_frame(rows=30), rank_window=10)

    assert scored["Risk_Score"].iloc[:6].isna().all()
    assert scored["CSV_Norm"].iloc[:4].isna().all()
    assert scored["Risk_Score"].iloc[6:].notna().all()


def test_fear_greed_v2_score_is_invariant_to_appended_future_metrics() -> None:
    metrics = _metrics_frame(rows=45)

    short = calculate_risk_score(metrics.iloc[:30], rank_window=10)
    full = calculate_risk_score(metrics, rank_window=10)

    assert_frame_equal(short, full.iloc[:30])


def test_fear_greed_v2_exposes_auditable_components() -> None:
    scored = calculate_risk_score(_metrics_frame(rows=35, mode="panic"), rank_window=10)
    latest = scored.iloc[-1]

    for column in [
        "Panic_Pull",
        "Fomo_Push",
        "CSV_Norm",
        "Dispersion_Stress",
        "Signal_Confidence",
    ]:
        assert column in scored.columns
        assert 0 <= latest[column] <= 1
    assert -1 <= latest["Net_Sentiment_Pressure"] <= 1

    assert latest["Methodology_Version"] == METHOD_VERSION
    assert latest["Panic_Pull"] > latest["Fomo_Push"]
    assert latest["Risk_Score"] < 40
    assert latest["Sentiment_Regime"] in {"EXTREME FEAR", "FEAR"}


def test_fear_greed_v2_identifies_greed_pressure() -> None:
    scored = calculate_risk_score(_metrics_frame(rows=35, mode="greed"), rank_window=10)
    latest = scored.iloc[-1]

    assert latest["Fomo_Push"] > latest["Panic_Pull"]
    assert latest["Risk_Score"] > 60
    assert latest["Sentiment_Regime"] in {"GREED", "EXTREME GREED"}


def test_fear_greed_v2_flags_margin_call_style_selloff() -> None:
    metrics = _metrics_frame(rows=80, mode="greed")
    metrics["Market_Factor"] = np.r_[
        np.full(75, 0.001),
        [-0.020, -0.025, -0.030, -0.020, -0.015],
    ]

    scored = calculate_risk_score(metrics, rank_window=20)
    latest = scored.iloc[-1]

    assert latest["Shock_Regime_Flag"] == "MARGIN_CALL_RISK"
    assert latest["Risk_Score_Raw"] <= 25
    assert latest["Risk_Score"] < 40
    assert latest["Sentiment_Regime"] == "FEAR"
