from __future__ import annotations

import pandas as pd

from tools.capitulation_regime import report


def test_capitulation_report_snapshot_flattens_engine_output(monkeypatch) -> None:
    close = pd.DataFrame(
        {"AAA": [100.0, 97.0], "BBB": [100.0, 96.0]},
        index=pd.to_datetime(["2026-07-21", "2026-07-22"]),
    )
    index_frame = pd.DataFrame(
        {"VNINDEX": [1200.0, 1164.0], "VNINDEX_VOLUME": [1000.0, 2500.0]},
        index=close.index,
    )

    class FakeSnapshot:
        def to_dict(self):
            return {
                "as_of": "2026-07-22T00:00:00",
                "phase": "CAPITULATION_CLIMAX",
                "sessions_after_three_gate_climax": 0,
                "stress_risk_score_uncalibrated": 82.44,
                "liquidation_risk_score_uncalibrated": 91.22,
                "exhaustion_evidence_score_uncalibrated": 12.0,
                "features": {
                    "return_1d": -0.03,
                    "return_5d": -0.08,
                    "drawdown": -0.12,
                    "ma200_gap": -0.1,
                    "breadth_ma20": 0.14,
                    "downside_participation": 0.83,
                    "new_low_252": 0.28,
                    "turnover_ratio_20": 1.7,
                },
                "percentiles": {"daily_loss": 0.97},
                "required_gates_met": {
                    "price_shock": True,
                    "breadth_shock": True,
                    "forced_selling": True,
                    "three_gate_climax": True,
                    "climax_continuation": False,
                    "post_climax_exhaustion": False,
                },
                "data_quality": {
                    "status": "GOOD",
                    "constituent_count": 2,
                    "current_breadth_coverage": 1.0,
                    "current_volume_coverage": 0.9,
                    "warnings": ["demo warning"],
                },
                "trigger_reasons": ["price shock"],
                "confirmation_reasons": [],
                "action_eligible": False,
                "methodology_version": "capitulation_state_machine_v2.0.0",
            }

    def fake_analyze(**kwargs):
        assert kwargs["index_close"].equals(index_frame["VNINDEX"])
        assert kwargs["constituent_close"].equals(close)
        assert kwargs["index_volume"].equals(index_frame["VNINDEX_VOLUME"])
        assert kwargs["abm_metrics"] == {"cascade_vulnerability": 70.0}
        assert kwargs["as_of"] == close.index[-1]
        return FakeSnapshot()

    monkeypatch.setattr(report, "load_volumes", lambda: close)
    monkeypatch.setattr(report, "_load_abm_metrics", lambda: {"cascade_vulnerability": 70.0})
    monkeypatch.setattr(report, "analyze_capitulation", fake_analyze)

    row = report.snapshot(close, lambda name: index_frame)

    assert row["snapshot_date"] == "2026-07-22"
    assert row["phase"] == "CAPITULATION_CLIMAX"
    assert row["sessions_after_three_gate_climax"] == 0
    assert row["action_eligible"] is False
    assert row["stress_risk_score_uncalibrated"] == 82.4
    assert row["liquidation_risk_score_uncalibrated"] == 91.2
    assert row["return_1d_pct"] == -3.0
    assert row["drawdown_pct"] == -12.0
    assert row["breadth_ma20_pct"] == 14.0
    assert row["downside_participation_pct"] == 83.0
    assert row["price_shock_gate"] is True
    assert row["climax_continuation_gate"] is False
    assert row["post_climax_exhaustion_gate"] is False
    assert row["data_quality_status"] == "GOOD"
    assert row["volume_coverage_pct"] == 90.0
    assert row["first_trigger_reason"] == "price shock"
    assert row["abm_metrics_used"] is True
    assert row["status"] == "ok"
