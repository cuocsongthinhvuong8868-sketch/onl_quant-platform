from __future__ import annotations

from dataclasses import dataclass

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
    monkeypatch.setattr(
        report,
        "johansen_test",
        lambda prices_arg: {"n_coint_vectors": 1, "valid_system": True},
    )
    monkeypatch.setattr(report, "engle_granger", fake_engle_granger)

    @dataclass
    class FakeResult:
        t1: str
        t2: str
        p_value: float
        q_value: float
        eligible: bool
        z_latest: float = 2.2

        def to_record(self) -> dict:
            return {
                "pair": f"{self.t1}/{self.t2}",
                "p_value": self.p_value,
                "q_value": self.q_value,
                "i1_valid": True,
                "eligible": self.eligible,
                "beta": 1.25,
                "half_life": 12.3,
                "z_score": self.z_latest,
                "rho_now": 0.7,
            }

    def fake_analyze_pair(prices_arg, t1, t2, config, *, q_value):
        p_value = 0.01 if {t1, t2} == {"AAA", "BBB"} else 0.2
        return FakeResult(t1, t2, p_value, q_value, q_value < 0.05)

    monkeypatch.setattr(report, "analyze_pair", fake_analyze_pair)

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
