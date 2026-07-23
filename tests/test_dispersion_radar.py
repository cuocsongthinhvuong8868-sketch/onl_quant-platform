from __future__ import annotations

import numpy as np
import pandas as pd

from tools.dispersion import report
from tools.dispersion.quant.metrics import (
    METHOD_VERSION,
    calculate_dispersion_metrics,
    determine_macro_regime,
    summarize_dispersion_state,
)


def test_dispersion_returns_do_not_forward_fill_missing_prices() -> None:
    dates = pd.date_range("2026-01-01", periods=45, freq="B")
    active = 100.0 * (1.001 ** np.arange(len(dates)))
    inactive = np.r_[100.0 * (1.001 ** np.arange(20)), np.full(len(dates) - 20, np.nan)]
    active[-1] = active[-2] * 0.96
    prices = pd.DataFrame({"ACTIVE": active, "INACTIVE": inactive}, index=dates)
    index = pd.Series(1000.0 * (1.0005 ** np.arange(len(dates))), index=dates)

    _, metrics = calculate_dispersion_metrics(prices, index, zscore_window=20, dpi_window=20)

    assert metrics["Effective_Names"].iloc[-1] == 1
    assert metrics["Downside_Participation"].iloc[-1] == 100.0


def test_dispersion_filters_implausible_bad_ticks() -> None:
    dates = pd.date_range("2026-01-01", periods=45, freq="B")
    normal = 100.0 * (1.001 ** np.arange(len(dates)))
    normal[-1] = normal[-2] * 0.96
    bad_tick = normal.copy()
    bad_tick[-1] = bad_tick[-2] * 3.0
    prices = pd.DataFrame({"NORMAL": normal, "BAD": bad_tick}, index=dates)
    index = pd.Series(1000.0 * (1.0005 ** np.arange(len(dates))), index=dates)

    _, metrics = calculate_dispersion_metrics(prices, index, zscore_window=20, dpi_window=20)

    assert metrics["Effective_Names"].iloc[-1] == 1
    assert np.isfinite(metrics["CSAD"].iloc[-1])


def test_dispersion_regime_flags_broad_selloff_stress() -> None:
    dates = pd.date_range("2026-01-01", periods=5, freq="B")
    metrics = pd.DataFrame(
        {
            "DPI": [40, 45, 48, 49, 48],
            "Ledoit_Correlation": [0.05] * 5,
            "Market_Return": [0.001, -0.002, -0.005, -0.01, -0.035],
            "CSAD_Z": [-0.5, 0.1, 0.2, 1.0, 3.2],
            "CSSD_Z": [-0.5, 0.1, 0.2, 0.5, 2.5],
            "Downside_Participation": [5, 8, 12, 20, 32],
            "Upside_Participation": [15, 12, 8, 6, 4],
        },
        index=dates,
    )

    regimes = determine_macro_regime(metrics)
    metrics["Macro_Regime"] = regimes
    summary = summarize_dispersion_state(metrics)

    assert regimes.iloc[-1] == "BROAD_SELLOFF_STRESS"
    assert summary["methodology_version"] == METHOD_VERSION
    assert summary["broad_stress_level"] in {"HIGH", "EXTREME"}


def test_dispersion_report_snapshot_exposes_v2_fields(monkeypatch) -> None:
    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    metrics = pd.DataFrame(
        {
            "Market_Return": np.r_[np.full(39, -0.001), -0.035],
            "CSAD": np.r_[np.full(39, 0.01), 0.03],
            "CSSD": np.r_[np.full(39, 0.015), 0.035],
            "CS_Skewness": np.zeros(40),
            "CS_Kurtosis": np.full(40, 3.0),
            "Spread": np.r_[np.full(39, 0.005), 0.005],
            "Spread_Z": np.r_[np.zeros(39), -1.1],
            "CSAD_Z": np.r_[np.zeros(39), 3.5],
            "CSSD_Z": np.r_[np.zeros(39), 2.4],
            "DPI": np.r_[np.full(39, 45.0), 48.0],
            "Downside_Participation": np.r_[np.full(39, 10.0), 30.0],
            "Upside_Participation": np.r_[np.full(39, 10.0), 5.0],
            "Effective_Names": np.full(40, 100),
        },
        index=dates,
    )
    stock_returns = pd.DataFrame({"AAA": np.zeros(40)}, index=dates)
    index_frame = pd.DataFrame({"VNINDEX": np.arange(40) + 1000.0}, index=dates)

    monkeypatch.setattr(report, "load_custom", lambda _name: index_frame)
    monkeypatch.setattr(report, "calculate_dispersion_metrics", lambda *_args, **_kwargs: (stock_returns, metrics.copy()))
    monkeypatch.setattr(report, "fit_rolling_correlation", lambda *_args, **_kwargs: pd.Series(0.05, index=dates))

    row = report.snapshot(pd.DataFrame(index=dates), None)

    assert row["snapshot_date"] == "2026-02-25"
    assert row["methodology_version"] == METHOD_VERSION
    assert row["macro_regime"] == "BROAD_SELLOFF_STRESS"
    assert row["broad_stress_level"] in {"HIGH", "EXTREME"}
    assert row["downside_participation_pct"] == 30.0
