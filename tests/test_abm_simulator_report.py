from __future__ import annotations

import pandas as pd
import pytest

from tools.abm_simulator import report


def test_abm_report_snapshot_reads_latest_outputs(tmp_path, monkeypatch) -> None:
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-16",
                "regime_flag": "SAFE_VALUE",
                "pct_fundamental": 0.25,
            },
            {
                "as_of_date": "2026-07-17",
                "regime_flag": "LEVERAGE_STRESS",
                "pct_fundamental": 0.22,
                "pct_momentum": 0.28,
                "pct_foreign": 0.18,
                "pct_leveraged": 0.2,
                "pct_noise": 0.12,
                "avg_leverage_ratio": 1.73456,
                "input_quality_score": 0.91,
                "qp_panel_available": True,
                "qp_panel_quality": 0.83,
                "mli": 0.64,
                "liquidity_stress": 0.42,
                "valuation_gap": -0.031,
                "trend_z": 1.25,
                "breadth_z": -0.44,
                "foreign_flow_z": -0.75,
                "margin_pressure_z": 1.88,
            },
        ]
    ).to_csv(tmp_path / "abm_behavioral_state.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-17",
                "panic_ratio": 0.35,
                "dd_total": -0.1234,
                "dd_exogenous": -0.08,
                "dd_endogenous": -0.0434,
                "margin_call_events": 7,
                "simulation_runs": 1000,
                "stress_confidence": 0.86,
            }
        ]
    ).to_csv(tmp_path / "abm_stress_test.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-17",
                "regime_flag": "CASCADE_RISK",
                "early_warning_score": 62.456,
                "early_warning_level": "ORANGE",
                "warning_basis": "distance_to_cascade,panic_ratio",
                "distance_to_cascade": 0.041,
                "stress_confidence": 0.87,
                "input_quality_score": 0.92,
                "methodology_version": "abm_v4",
            }
        ]
    ).to_csv(tmp_path / "abm_alert.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-17",
                "margin_leverage_level": 0.73,
                "margin_call_trigger_pressure": 0.68,
                "cascade_vulnerability": 0.57,
                "latent_confidence_score": 0.88,
                "validation_status": "validated",
                "validation_quality": 0.79,
            }
        ]
    ).to_csv(tmp_path / "abm_latent_state.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-17",
                "validation_status": "fallback",
                "auc": 0.71234,
                "lift_top_decile": 1.9234,
            }
        ]
    ).to_csv(tmp_path / "abm_validation.csv", index=False)
    monkeypatch.setattr(report, "DATA_LAKE", tmp_path)

    row = report.snapshot()

    assert row["snapshot_date"] == "2026-07-17"
    assert row["regime_flag"] == "CASCADE_RISK"
    assert row["early_warning_score"] == 62.46
    assert row["early_warning_level"] == "ORANGE"
    assert row["warning_basis_display"] == "Distance to cascade; Panic ratio"
    assert row["uses_quant_platform_panel"] is True
    assert row["distance_to_cascade_pct"] == 4.1
    assert row["panic_ratio_pct"] == 35.0
    assert row["dd_total_pct"] == -12.34
    assert row["stress_confidence_pct"] == 87.0
    assert row["input_quality_score_pct"] == 92.0
    assert row["pct_leveraged"] == 20.0
    assert row["avg_leverage_ratio"] == 1.7346
    assert row["margin_call_events"] == 7
    assert row["simulation_runs"] == 1000
    assert row["margin_leverage_level"] == 0.73
    assert row["validation_status"] == "validated"
    assert row["validation_quality_pct"] == 79.0
    assert row["validation_auc"] == 0.7123
    assert row["top_decile_event_lift"] == 1.9234
    assert row["methodology_version"] == "abm_v4"
    assert row["status"] == "ok"


def test_abm_report_snapshot_requires_core_outputs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "DATA_LAKE", tmp_path)

    with pytest.raises(FileNotFoundError, match="abm_behavioral_state.csv"):
        report.snapshot()
