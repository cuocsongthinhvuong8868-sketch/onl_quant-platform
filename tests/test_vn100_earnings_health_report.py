from __future__ import annotations

import json

import pandas as pd

from tools.vn100_earnings_health import report


def test_vn100_report_snapshot_reads_latest_yoy_outputs(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "tickers": 100,
                "periods": 33,
                "latest_qoq_period": "2026Q1",
                "latest_yoy_period": "2025Q4",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "period": "2025Q4",
                "vn100_health_score": 49.5991832,
                "vn100_health_score_market_cap_weighted": 49.9481169,
                "valid_company_count": 99,
                "positive_sector_count": 0,
                "valid_sector_count": 16,
                "regime": "Mixed / Divergent",
                "revenue_breadth": 0.8282828,
                "profit_breadth": 0.8484848,
                "cfo_breadth": 0.5656565,
                "healthy_growth_breadth": 0.3232323,
                "working_capital_stress_index": 49.4900612,
                "leverage_stress_index": 49.603386,
                "sector_diffusion_score": 0.0,
                "main_diagnosis": json.dumps(["Revenue recovery", "Cashflow weak"]),
            }
        ]
    ).to_csv(output_dir / "vn100_scores_latest_yoy.csv", index=False)
    pd.DataFrame(
        [
            {"sector": "Banks", "sector_health_score": 55.0},
            {"sector": "Real Estate", "sector_health_score": 42.0},
        ]
    ).to_csv(output_dir / "sector_scores_latest_yoy.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "AAA", "alert_level": "Warning"},
            {"ticker": "BBB", "alert_level": "Critical"},
        ]
    ).to_csv(output_dir / "alerts.csv", index=False)
    monkeypatch.setattr(report, "OUTPUT_DIR", output_dir)

    row = report.snapshot()

    assert row["snapshot_date"] == "2025Q4"
    assert row["vn100_health_score"] == 49.5992
    assert row["ticker_count"] == 100
    assert row["top_sector"] == "Banks"
    assert row["weakest_sector"] == "Real Estate"
    assert row["critical_alert_count"] == 1
    assert row["top_critical_alert_ticker"] == "BBB"
    assert row["main_diagnosis"] == "Revenue recovery; Cashflow weak"
    assert row["status"] == "ok"
