from __future__ import annotations

import pandas as pd

from tools.data_health import report


def test_data_health_report_snapshot_summarizes_manager_output(monkeypatch) -> None:
    class FakeManager:
        def __init__(self, as_of):
            assert as_of.isoformat() == "2026-07-22"

        def check_data_freshness(self):
            return {
                "as_of": "2026-07-22",
                "overall_status": "warning",
                "summary": {"source_count": 3, "healthy": 1, "warning": 1, "critical": 1},
                "sources": [
                    {
                        "name": "market_data",
                        "category": "raw/market",
                        "status": "healthy",
                        "latest_data_date": "2026-07-22",
                        "freshness_days": 0,
                    },
                    {
                        "name": "factor_cache",
                        "category": "processed/tool_metrics",
                        "status": "warning",
                        "latest_data_date": "2026-07-20",
                        "freshness_days": 2,
                        "cache_status": "warning",
                    },
                    {
                        "name": "old_report",
                        "category": "processed/reports",
                        "status": "critical",
                        "latest_data_date": None,
                        "freshness_days": None,
                    },
                ],
            }

    monkeypatch.setattr(report, "DataManager", FakeManager)
    close = pd.DataFrame({"AAA": [1, 2]}, index=pd.to_datetime(["2026-07-21", "2026-07-22"]))

    row = report.snapshot(close)

    assert row["snapshot_date"] == "2026-07-22"
    assert row["overall_status"] == "warning"
    assert row["source_count"] == 3
    assert row["healthy_count"] == 1
    assert row["warning_count"] == 1
    assert row["critical_count"] == 1
    assert row["raw_source_count"] == 1
    assert row["processed_source_count"] == 2
    assert row["tool_metric_count"] == 1
    assert row["report_source_count"] == 1
    assert row["missing_or_undated_count"] == 1
    assert row["cache_issue_count"] == 1
    assert row["most_stale_source"] == "factor_cache"
    assert row["most_stale_age_days"] == 2
    assert row["status"] == "ok"
