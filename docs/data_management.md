# Model D - Data Management

Model D monitors the freshness of files in `data_lake` and reports whether each source is healthy, stale, or critical.

The dashboard tracks two different layers:

- Raw / persisted files: CSV, JSON, and Parquet files that physically exist in `data_lake`.
- Tool metrics: derived metric availability for each analytical tool. These rows use the latest date of their configured dependencies, and include cache metadata when the tool writes a model cache to `data_lake/daily_cache`.

## Files

- `src/data_manager.py`: core scanner, freshness rules, gap detection, JSON/CSV export.
- `src/utils/date_parser.py`: date parsing from file names and date-like values.
- `config/data_rules.yaml`: monitored sources and warning/critical thresholds.
- `pages/D_Data_Health.py`: Streamlit dashboard.
- `command/data_health_report.py`: CLI report generator.

## Add A New Source

Add a new item under `sources` in `config/data_rules.yaml`:

```yaml
- name: my_source
  category: raw/market
  path: data_lake/my_source.csv
  warning_days: 1
  critical_days: 4
  frequency: business_daily
  date_columns: [time, date, DATE]
```

Use `raw/market`, `raw/macro`, `raw/sentiment`, `processed/metrics`, or another category that matches how you want to filter the source.

For a tool metric that is computed from other sources, use `type: tool_metrics`:

```yaml
- name: metrics_market_breadth
  category: processed/tool_metrics/behavioral
  type: tool_metrics
  tool: Market Breadth
  depends_on: [market_data]
  cache_namespace: market_breadth
  warning_days: 1
  critical_days: 4
```

`depends_on` should reference source names already defined in the same file. `cache_namespace` is optional and is used only to display cache freshness.

## CLI

```bash
python command/data_health_report.py
python command/data_health_report.py --format json --output reports/data_health.json
python command/data_health_report.py --format csv --output reports/data_health.csv
```

## API Usage

```python
from src.data_manager import DataManager

manager = DataManager()
report = manager.check_data_freshness()
latest_market = manager.get_latest_raw_date("market")
latest_metrics = manager.get_latest_metrics_date()
gaps = manager.detect_gaps("2026-06-01", "2026-06-05", source_name="market_data")
```
