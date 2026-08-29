from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.upside_ratio import report
from tools.upside_ratio.quant import engine
from tools.upside_ratio.quant.metrics import (
    METHOD_VERSION,
    build_breadth_series,
    summarize_breadth_state,
)


def test_upside_ratio_returns_do_not_forward_fill_missing_prices() -> None:
    dates = pd.date_range("2026-01-01", periods=50, freq="B")
    active = 100.0 * (1.001 ** np.arange(len(dates)))
    active[-1] = active[-2] * 0.97
    inactive = np.r_[100.0 * (1.001 ** np.arange(15)), np.full(len(dates) - 15, np.nan)]
    prices = pd.DataFrame({"ACTIVE": active, "INACTIVE": inactive}, index=dates)

    data = build_breadth_series(prices, upside_x=2.0, downside_y=-2.0, lookback_days=35)

    assert data["raw_downside"].iloc[-1] == 100.0
    assert data["raw_upside"].iloc[-1] == 0.0


def test_upside_ratio_summary_flags_downside_stress() -> None:
    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    raw_upside = pd.Series(np.r_[np.full(39, 12.0), 5.0], index=dates)
    raw_downside = pd.Series(np.r_[np.linspace(3.0, 18.0, 39), 30.0], index=dates)
    data = {
        "raw_upside": raw_upside,
        "ma5_upside": raw_upside.rolling(5).mean().dropna(),
        "raw_downside": raw_downside,
        "ma5_downside": raw_downside.rolling(5).mean().dropna(),
    }

    summary = summarize_breadth_state(data)

    assert summary["methodology_version"] == METHOD_VERSION
    assert summary["breadth_regime"] == "DOWNSIDE_STRESS"
    assert summary["breadth_stress_level"] in {"HIGH", "EXTREME"}
    assert summary["net_pressure"] == 25.0


def test_upside_ratio_autoreg_is_compatible_with_statsmodels_015(monkeypatch) -> None:
    class AutoRegWithoutOldNames:
        def __init__(self, endog, lags):
            assert lags == 1
            self.endog = np.asarray(endog)

        def fit(self):
            return SimpleNamespace(
                params=np.array([0.05, 0.90]),
                resid=np.diff(self.endog),
            )

    monkeypatch.setattr(engine, "AutoReg", AutoRegWithoutOldNames)
    series = pd.Series(np.linspace(10.0, 70.0, 40))

    result = engine.run_hybrid_ensemble_mc(series, days_to_sim=3, num_sims=20)

    assert all(len(percentile) == 3 for percentile in result[:5])


def test_upside_ratio_report_exposes_v2_stress_fields(monkeypatch) -> None:
    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    raw_upside = pd.Series(np.r_[np.full(39, 12.0), 5.0], index=dates)
    raw_downside = pd.Series(np.r_[np.linspace(3.0, 18.0, 39), 30.0], index=dates)
    data = {
        "raw_upside": raw_upside,
        "ma5_upside": raw_upside.rolling(5).mean().dropna(),
        "raw_downside": raw_downside,
        "ma5_downside": raw_downside.rolling(5).mean().dropna(),
    }

    def fake_mc(*_args, **_kwargs):
        values = np.full(10, 11.0)
        return values, values, values, values, values, 0.2, 0.1, np.array([0.0]), np.array([0.0])

    monkeypatch.setattr(report, "build_breadth_series", lambda *_args, **_kwargs: data)
    monkeypatch.setattr(report, "run_hybrid_ensemble_mc", fake_mc)

    row = report.snapshot(pd.DataFrame(index=dates), None)

    assert row["snapshot_date"] == "2026-02-25"
    assert row["methodology_version"] == METHOD_VERSION
    assert row["breadth_regime"] == "DOWNSIDE_STRESS"
    assert row["downside_rank"] == 1.0
    assert row["net_pressure"] == 25.0
