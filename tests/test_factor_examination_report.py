from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factor_examination import report


def test_factor_examination_report_snapshot_builds_universe_summary(monkeypatch) -> None:
    dates = pd.date_range("2026-06-01", periods=40, freq="D")
    tickers = [f"T{i:02d}" for i in range(31)]
    prices = pd.DataFrame(
        np.full((len(dates), len(tickers)), 100.0),
        index=dates,
        columns=tickers,
    )
    volumes = pd.DataFrame(
        np.full((len(dates), len(tickers)), 20_000.0),
        index=dates,
        columns=tickers,
    )
    composite_values = [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8]
    composite_values += list(np.linspace(0.7, -0.9, 17))
    composite_values += [-1.0, -1.1, -1.2, -1.3, -1.4, -1.5]
    composite = pd.Series(composite_values, index=tickers, name="composite")
    rank_pct = composite.rank(pct=True) * 100.0
    z_table = pd.DataFrame(
        {
            "Mom_12_1": np.linspace(2.0, -2.0, len(tickers)),
            "LowVol": np.linspace(-1.0, 1.0, len(tickers)),
        },
        index=tickers,
    )
    sector_map = pd.Series(
        ["Banks"] * 5 + ["Steel"] * 10 + ["Securities"] * 16,
        index=tickers,
    )

    monkeypatch.setattr(report, "load_volumes", lambda: volumes)
    monkeypatch.setattr(report, "load_ticker_metadata", lambda: pd.DataFrame({"sector": sector_map}))
    monkeypatch.setattr(
        report,
        "compute_all_factors",
        lambda prices_arg, volumes_arg, market_arg: pd.DataFrame(index=tickers),
    )
    monkeypatch.setattr(
        report,
        "build_score_table",
        lambda factors, metadata, sector_neutral: {
            "composite": composite,
            "rank_pct": rank_pct,
            "z": z_table,
            "sector_map": sector_map,
        },
    )

    row = report.snapshot(
        prices,
        lambda name: pd.DataFrame({"VNINDEX": np.arange(len(dates)) + 1000.0}, index=dates),
    )

    assert row["snapshot_date"] == "2026-07-10"
    assert row["sector_neutral"] is True
    assert row["universe_count"] == 31
    assert row["valid_ticker_count"] == 31
    assert row["strong_count"] == 8
    assert row["weak_count"] == 6
    assert row["top_ticker"] == "T00"
    assert row["top_composite_z"] == 1.5
    assert row["top_rank_pct"] == 100.0
    assert row["top_sector"] == "Banks"
    assert row["top_factor"] == "Mom_12_1"
    assert row["weakest_ticker"] == "T30"
    assert row["weakest_factor"] == "Mom_12_1"
    assert row["top_decile_sector"] == "Banks"
    assert row["bottom_decile_sector"] == "Securities"
    assert row["metadata_available"] is True
    assert row["status"] == "ok"
