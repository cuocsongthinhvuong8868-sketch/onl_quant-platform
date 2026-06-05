from __future__ import annotations

from datetime import date

from src.data_manager import DataManager
from src.utils.date_parser import extract_dates_from_text, parse_date_value


def test_extract_dates_from_common_file_names() -> None:
    assert max(extract_dates_from_text("04062026.json")) == date(2026, 6, 4)
    assert max(extract_dates_from_text("executive_summary_deepseek-v4-pro_040626.txt")) == date(2026, 6, 4)
    assert parse_date_value("2026-06-05") == date(2026, 6, 5)
    assert parse_date_value("5/13/2019") == date(2019, 5, 13)


def test_data_manager_reads_latest_raw_and_metrics_dates(tmp_path) -> None:
    data_lake = tmp_path / "data_lake"
    outputs = data_lake / "vn100_earnings_health" / "outputs"
    outputs.mkdir(parents=True)

    (data_lake / "market_data.csv").write_text(
        "time,AAA\n2026-06-02,1\n2026-06-04,2\n",
        encoding="utf-8",
    )
    (outputs / "ticker_metrics.csv").write_text(
        "period_end_date,ticker\n2026-03-31,AAA\n2026-06-30,AAA\n",
        encoding="utf-8",
    )

    manager = DataManager(root_dir=tmp_path, config_path=tmp_path / "missing.yaml", as_of=date(2026, 6, 5))

    assert manager.get_latest_raw_date("market") == date(2026, 6, 4)
    assert manager.get_latest_metrics_date() == date(2026, 6, 30)


def test_data_freshness_handles_missing_files(tmp_path) -> None:
    (tmp_path / "data_lake").mkdir()
    manager = DataManager(root_dir=tmp_path, config_path=tmp_path / "missing.yaml", as_of=date(2026, 6, 5))

    report = manager.check_data_freshness()

    assert report["overall_status"] == "critical"
    assert report["summary"]["critical"] > 0


def test_detect_gaps_uses_business_days(tmp_path) -> None:
    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    (data_lake / "market_data.csv").write_text(
        "time,AAA\n2026-06-02,1\n2026-06-04,2\n",
        encoding="utf-8",
    )
    manager = DataManager(root_dir=tmp_path, config_path=tmp_path / "missing.yaml", as_of=date(2026, 6, 5))

    gaps = manager.detect_gaps("2026-06-02", "2026-06-04", source_name="market_data")

    assert gaps == [date(2026, 6, 3)]


def test_tool_metrics_status_is_derived_from_dependencies(tmp_path) -> None:
    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    (data_lake / "market_data.csv").write_text(
        "time,AAA\n2026-06-02,1\n2026-06-04,2\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "data_rules.yaml"
    config_path.write_text(
        """
data_lake: data_lake
defaults:
  warning_days: 1
  critical_days: 4
  date_columns: [time, date, DATE]
sources:
  - name: market_data
    category: raw/market
    path: data_lake/market_data.csv
    warning_days: 1
    critical_days: 4
    frequency: business_daily
    date_columns: [time]
  - name: metrics_market_breadth
    category: processed/tool_metrics/behavioral
    type: tool_metrics
    tool: Market Breadth
    depends_on: [market_data]
    warning_days: 1
    critical_days: 4
""",
        encoding="utf-8",
    )
    manager = DataManager(root_dir=tmp_path, config_path=config_path, as_of=date(2026, 6, 5))

    report = manager.check_data_freshness()
    metric = next(source for source in report["sources"] if source["name"] == "metrics_market_breadth")

    assert metric["latest_data_date"] == "2026-06-04"
    assert metric["status"] == "healthy"
    assert metric["dependencies"] == "market_data"
