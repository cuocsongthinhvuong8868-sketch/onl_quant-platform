from __future__ import annotations

import json

import pytest

from tools.ltmm import report


def test_ltmm_report_snapshot_reads_latest_source_json(tmp_path, monkeypatch) -> None:
    older = tmp_path / "20072026.json"
    older.write_text(json.dumps({"latest_indices": []}), encoding="utf-8")
    latest = tmp_path / "21072026.json"
    latest.write_text(
        json.dumps(
            {
                "latest_indices": [
                    {
                        "as_of_date": "2026-07-21",
                        "index_name": "FLI",
                        "index_value": 0.8,
                        "state": "tightening",
                        "quality_score": 0.76,
                        "quality_state": "usable",
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "index_name": "MLI",
                        "index_value": 0.95,
                        "state": "stress",
                        "quality_score": 0.61,
                        "quality_state": "usable",
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "index_name": "TE",
                        "index_value": -0.2,
                        "state": "neutral",
                        "quality_score": 0.7,
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "index_name": "FRI_collateral",
                        "index_value": 0.42,
                        "state": "neutral",
                        "quality_state": "warning",
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "index_name": "FRI_risk",
                        "index_value": 0.31,
                        "state": "neutral",
                    },
                ],
                "bottlenecks": [
                    {
                        "constraint": "Secondary constraint",
                        "layer": "MLI",
                        "stress_score": 0.2,
                        "state": "neutral",
                        "quality": "OK",
                        "observation_date": "2026-07-21",
                    },
                    {
                        "constraint": "Equity-rate wedge",
                        "layer": "BND",
                        "stress_score": 1.55,
                        "state": "stress",
                        "quality": "LOW_VNINDEX_PE_PROXY",
                        "observation_date": "2026-07-20",
                    },
                ],
                "overlays": [
                    {
                        "overlay": "Ignored footprint",
                        "node": "BND",
                        "stress_score": 9.0,
                        "state": "stress",
                    },
                    {
                        "overlay": "Foreign flow 5d pressure",
                        "node": "MLI",
                        "stress_score": 0.49,
                        "state": "neutral",
                    },
                    {
                        "overlay": "Equity-rate wedge",
                        "node": "BND",
                        "stress_score": 1.55,
                        "state": "stress",
                    },
                ],
                "triggers": [
                    {
                        "as_of_date": "2026-07-21",
                        "trigger_id": "transmission_breakdown",
                        "signal_state": "FIRE",
                        "fresh_conditions_met": 3,
                        "fresh_conditions_total": 3,
                        "conditions_excluded": 0,
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "trigger_id": "banking_funding_squeeze",
                        "signal_state": "non-fire",
                        "fresh_conditions_met": 2,
                        "fresh_conditions_total": 3,
                        "conditions_excluded": 1,
                    },
                    {
                        "as_of_date": "2026-07-21",
                        "trigger_id": "far_from_fire",
                        "signal_state": "non-fire",
                        "fresh_conditions_met": 0,
                        "fresh_conditions_total": 3,
                        "conditions_excluded": 2,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(report, "SOURCE_DIR", tmp_path)

    row = report.snapshot()

    assert row["snapshot_date"] == "2026-07-21"
    assert row["source_file"] == "21072026.json"
    assert row["headline_state"] == "ALERT"
    assert row["fli"] == 0.8
    assert row["mli"] == 0.95
    assert row["transmission_gap"] == 0.15
    assert row["transmission_gap_state"] == "contained_gap"
    assert row["fli_quality_score"] == 0.76
    assert row["fri_collateral_quality_state"] == "warning"
    assert row["fire_trigger_count"] == 1
    assert row["near_fire_trigger_count"] == 1
    assert row["transmission_breakdown_fire"] is True
    assert row["excluded_condition_count"] == 3
    assert row["top_fire_trigger_id"] == "transmission_breakdown"
    assert row["top_near_fire_trigger_id"] == "banking_funding_squeeze"
    assert row["primary_bottleneck"] == "Equity-rate wedge"
    assert row["primary_bottleneck_stress_score"] == 1.55
    assert row["strongest_key_overlay"] == "Equity-rate wedge"
    assert row["key_overlay_count"] == 2
    assert row["status"] == "ok"


def test_ltmm_report_snapshot_requires_source_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "SOURCE_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="LTMM source JSON"):
        report.snapshot()
