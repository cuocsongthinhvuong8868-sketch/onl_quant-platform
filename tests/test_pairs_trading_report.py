from __future__ import annotations

import numpy as np
import pandas as pd

from tools.pairs_trading import report


def test_pairs_trading_report_snapshot_scans_predefined_clusters(monkeypatch) -> None:
    dates = pd.date_range("2026-01-01", periods=140, freq="D")
    prices = pd.DataFrame(
        {
            "AAA": np.linspace(100, 140, len(dates)),
            "BBB": np.linspace(101, 141, len(dates)),
            "CCC": np.linspace(80, 90, len(dates)),
        },
        index=dates,
    )

    def fake_engle_granger(series_1, series_2):
        pair = {series_1.name, series_2.name}
        p_value = 0.01 if pair == {"AAA", "BBB"} else 0.2
        return {
            "beta": 1.25,
            "p_value": p_value,
            "is_cointegrated": p_value < 0.05,
            "resid": pd.Series(np.linspace(-1, 1, len(series_1)), index=series_1.index),
            "n_obs": len(series_1),
        }

    monkeypatch.setattr(report, "PREDEFINED_CLUSTERS", {"Test": ["AAA", "BBB", "CCC"]})
    monkeypatch.setattr(report, "johansen_test", lambda prices_arg: {"n_coint_vectors": 1})
    monkeypatch.setattr(report, "engle_granger", fake_engle_granger)
    monkeypatch.setattr(report, "ou_half_life_raw", lambda resid: 12.3)
    monkeypatch.setattr(
        report,
        "z_score_60d",
        lambda resid: pd.Series([2.2] * len(resid), index=resid.index),
    )

    row = report.snapshot(prices)

    assert row["snapshot_date"] == "2026-05-20"
    assert row["cluster_count"] == 1
    assert row["evaluated_cluster_count"] == 1
    assert row["total_pair_count"] == 3
    assert row["cointegrated_pair_count"] == 1
    assert row["tradable_pair_count"] == 1
    assert row["entry_signal_count"] == 1
    assert row["best_cluster"] == "Test"
    assert row["best_pair"] == "AAA/BBB"
    assert row["best_p_value"] == 0.01
    assert row["best_half_life"] == 12.3
    assert row["best_z_score"] == 2.2
    assert row["best_signal"] == "ENTRY_SHORT_SPREAD"
    assert row["top_johansen_cluster"] == "Test"
    assert row["top_johansen_coint_vectors"] == 1
    assert row["status"] == "ok"
