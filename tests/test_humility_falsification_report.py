from __future__ import annotations

import json

import pytest

from tools.humility_falsification import report


def test_humility_report_snapshot_reads_latest_cache(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "daily_cache"
    cache_dir.mkdir()
    (cache_dir / "humility_falsification_test-provider_210726.json").write_text(
        json.dumps({"t_data_date": "2026-07-21", "rows": []}),
        encoding="utf-8",
    )
    (cache_dir / "humility_falsification_test-provider_220726.json").write_text(
        json.dumps(
            {
                "provider_key": "test-provider",
                "t_data_date": "2026-07-22",
                "target_report_date": "2026-07-21",
                "report_name": "executive_summary_test-provider_210726.txt",
                "report_match": "exact",
                "parsed": {
                    "report_date": "2026-07-21",
                    "composite_score": 21.0,
                    "regime": "PRE-CRASH / PANIC",
                    "parse_mode": "sidecar JSON",
                },
                "rows": [
                    {
                        "Model": "VNIBOR Monitor",
                        "Metric": "STRESS/WARNING sessions (20D)",
                        "T-1 threshold": "< 5 sessions",
                        "T actual": 4.0,
                        "Status": "FALSIFIED",
                        "Data date": "2026-07-20",
                        "Falsified": True,
                    },
                    {
                        "Model": "Market Breadth",
                        "Metric": "Breadth MA20",
                        "T-1 threshold": "> 45.0%",
                        "T actual": 6.1,
                        "Status": "Intact",
                        "Data date": "2026-07-22",
                        "Falsified": False,
                    },
                ],
                "current_metrics": {
                    "vnibor": {"value": 4, "date": "2026-07-20", "error": ""},
                    "evt": {"value": None, "date": "", "error": "missing EVT"},
                },
                "status_label": "WATCH",
                "status_help": "Some rules triggered",
                "falsified": 1,
                "available": 2,
                "total": 2,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(report, "DATA_LAKE", tmp_path)

    row = report.snapshot()

    assert row["snapshot_date"] == "2026-07-22"
    assert row["target_report_date"] == "2026-07-21"
    assert row["provider_key"] == "test-provider"
    assert row["cache_file"] == "humility_falsification_test-provider_220726.json"
    assert row["report_name"] == "executive_summary_test-provider_210726.txt"
    assert row["source_composite_score"] == 21.0
    assert row["source_regime"] == "PRE-CRASH / PANIC"
    assert row["thesis_status"] == "WATCH"
    assert row["falsified_rule_count"] == 1
    assert row["available_metric_count"] == 2
    assert row["total_rule_count"] == 2
    assert row["falsification_ratio_pct"] == 50.0
    assert row["thesis_falsified"] is False
    assert row["first_falsified_model"] == "VNIBOR Monitor"
    assert row["first_falsified_actual"] == 4.0
    assert row["metric_error_count"] == 1
    assert row["metric_min_date"] == "2026-07-20"
    assert row["metric_max_date"] == "2026-07-22"
    assert row["status"] == "ok"


def test_humility_report_snapshot_requires_cache(tmp_path, monkeypatch) -> None:
    (tmp_path / "daily_cache").mkdir()
    monkeypatch.setattr(report, "DATA_LAKE", tmp_path)

    with pytest.raises(FileNotFoundError, match="Humility/Falsification cache"):
        report.snapshot()
