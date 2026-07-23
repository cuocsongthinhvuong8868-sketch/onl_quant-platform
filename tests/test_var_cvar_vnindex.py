import numpy as np
import pandas as pd

from shared.data_loader import load_close_prices
from tools.var_cvar_vnindex.quant.metrics import (
    METHOD_VERSION,
    calculate_var_cvar_metrics,
    summarize_var_cvar_state,
)
from tools.var_cvar_vnindex.report import snapshot


def _price_series(returns: list[float]) -> pd.Series:
    prices = [100.0]
    for daily_return in returns:
        prices.append(prices[-1] * (1.0 + daily_return))
    return pd.Series(prices, index=pd.date_range("2024-01-01", periods=len(prices), freq="D"))


def test_var_cvar_classic_uses_prior_window_for_same_day_var():
    series = _price_series([0.01] * 8 + [-0.20])

    metrics = calculate_var_cvar_metrics(
        series,
        include_evt=False,
        hist_window=5,
        stddev_window=5,
        max_abs_simple_return=1.0,
    )
    latest = metrics.iloc[-1]

    assert np.isclose(latest["simple_return"], -0.20)
    assert latest["historical_var"] > 0
    assert bool(latest["var_breach_95"])
    assert latest["breach_margin_95"] > 0.20


def test_var_cvar_bad_ticks_are_removed_from_returns():
    series = pd.Series(
        [100.0, 101.0, 1.0, 102.0, 103.0],
        index=pd.date_range("2024-01-01", periods=5, freq="D"),
    )

    metrics = calculate_var_cvar_metrics(
        series,
        include_evt=False,
        hist_window=2,
        stddev_window=2,
        max_abs_simple_return=0.50,
    )

    assert bool(metrics["bad_return_flag"].iloc[2])
    assert bool(metrics["bad_return_flag"].iloc[3])
    assert np.isnan(metrics["return"].iloc[2])
    assert np.isnan(metrics["return"].iloc[3])


def test_var_cvar_summary_flags_active_tail_stress():
    latest = pd.Series(
        {
            "return": -0.04,
            "historical_var": -0.02,
            "breach_margin_95": 0.02,
            "var_breach_95": True,
            "evt_xi": 0.34,
        }
    )
    sensitivity = pd.DataFrame(
        {
            "status": ["ok", "ok", "ok"],
            "xi": [0.16, 0.25, 0.34],
            "evt_var_99": [-0.034, -0.037, -0.038],
            "evt_es_99": [-0.055, -0.061, -0.065],
        }
    )

    summary = summarize_var_cvar_state(latest, sensitivity=sensitivity)

    assert summary["methodology_version"] == METHOD_VERSION
    assert summary["tail_regime"] == "TAIL_STRESS_ACTIVE"
    assert summary["tail_risk_level"] == "HIGH"


def test_var_cvar_report_snapshot_exposes_v3_fields():
    snap = snapshot(load_close_prices())

    assert snap["methodology_version"] == METHOD_VERSION
    assert snap["snapshot_date"]
    assert "tail_regime" in snap
    assert "current_return" in snap
    assert "var_breach_95" in snap
    assert "evt_gaussian_var99_gap" in snap
