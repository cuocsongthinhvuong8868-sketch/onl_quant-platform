from __future__ import annotations

import csv
import json
import pickle
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from src.utils.date_parser import extract_dates_from_text, latest_date, parse_date_value


SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json"}


DEFAULT_CONFIG: dict[str, Any] = {
    "data_lake": "data_lake",
    "defaults": {
        "warning_days": 2,
        "critical_days": 7,
        "frequency": "daily",
        "recursive": True,
        "file_patterns": ["*.csv", "*.parquet", "*.json"],
        "date_columns": ["date", "DATE", "time", "period_end_date", "ddmmyyyy"],
    },
    "sources": [
        {
            "name": "market_data",
            "category": "raw/market",
            "path": "data_lake/market_data.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["time", "date", "DATE"],
        },
        {
            "name": "market_volume",
            "category": "raw/market",
            "path": "data_lake/market_volume.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["time", "date", "DATE"],
        },
        {
            "name": "vnindex_cache",
            "category": "raw/market",
            "path": "data_lake/vnindex_cache.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["time", "date", "DATE"],
        },
        {
            "name": "vn30_cache",
            "category": "raw/market",
            "path": "data_lake/vn30_cache.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["time", "date", "DATE"],
        },
        {
            "name": "vnibor",
            "category": "raw/macro",
            "path": "data_lake/LaiSuatLienNganHang_Wichart.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["date", "DATE", "time"],
        },
        {
            "name": "fed_liquidity",
            "category": "raw/macro",
            "path": "data_lake/fed_liquidity_cache.csv",
            "warning_days": 7,
            "critical_days": 21,
            "frequency": "weekly",
            "date_columns": ["DATE", "date", "time"],
        },
        {
            "name": "global_financial_conditions",
            "category": "raw/macro",
            "path": "data_lake/global_financial_conditions_cache.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["DATE", "date", "time"],
        },
        {
            "name": "ltmm_raw",
            "category": "raw/macro",
            "path": "data_lake/data_LTMM/sourse_raw",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "daily",
            "file_patterns": ["*.json"],
        },
        {
            "name": "manipulation_raw",
            "category": "raw/sentiment",
            "path": "data_lake/manipulation_raw_data.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "business_daily",
            "date_columns": ["date", "DATE", "time"],
        },
        {
            "name": "vn100_ticker_metrics",
            "category": "processed/metrics",
            "path": "data_lake/vn100_earnings_health/outputs/ticker_metrics.csv",
            "warning_days": 120,
            "critical_days": 210,
            "frequency": "quarterly",
            "date_columns": ["period_end_date", "date", "DATE"],
        },
        {
            "name": "vn100_composite",
            "category": "processed/metrics",
            "path": "data_lake/vn100_earnings_health/outputs/vn100_composite.csv",
            "warning_days": 120,
            "critical_days": 210,
            "frequency": "quarterly",
            "date_columns": ["period_end_date", "date", "DATE"],
        },
        {
            "name": "ai_cio_score_history",
            "category": "processed/reports",
            "path": "data_lake/Ai_cio_report.csv",
            "warning_days": 3,
            "critical_days": 10,
            "frequency": "daily",
            "date_columns": ["ddmmyyyy", "date", "DATE"],
        },
    ],
}


@dataclass(frozen=True)
class FileRecord:
    path: Path
    data_date: date | None
    date_source: str
    mtime: datetime
    error: str | None = None


def _load_config(config_path: Path | None) -> dict[str, Any]:
    if not config_path or not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)

    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return deepcopy(DEFAULT_CONFIG)

    config = deepcopy(DEFAULT_CONFIG)
    config.update({key: value for key, value in loaded.items() if key != "defaults"})
    config["defaults"].update(loaded.get("defaults") or {})
    if loaded.get("sources"):
        config["sources"] = loaded["sources"]
    return config


class DataManager:
    """Scan data_lake files and report data freshness.

    The class is designed to work with the planned raw/processed layout and the
    current repository layout where key CSV files live directly under data_lake.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        config_path: str | Path | None = None,
        as_of: date | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve() if root_dir else Path(__file__).resolve().parents[1]
        self.config_path = Path(config_path).resolve() if config_path else self.root_dir / "config" / "data_rules.yaml"
        self.config = _load_config(self.config_path)
        self.as_of = as_of or date.today()

        data_lake = Path(str(self.config.get("data_lake", "data_lake")))
        self.data_lake = data_lake if data_lake.is_absolute() else self.root_dir / data_lake
        self.defaults = self.config.get("defaults", {})
        self.rules = [self._normalize_rule(rule) for rule in self.config.get("sources", [])]
        self.rule_by_name = {str(rule["name"]): rule for rule in self.rules}
        self._status_cache: dict[str, dict[str, Any]] = {}

    def _normalize_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self.defaults)
        merged.update(rule)
        merged["name"] = str(merged.get("name") or merged.get("path") or "unnamed_source")
        merged["category"] = str(merged.get("category") or "raw")
        merged["warning_days"] = int(merged.get("warning_days", 2))
        merged["critical_days"] = int(merged.get("critical_days", max(merged["warning_days"] + 1, 7)))
        merged["recursive"] = bool(merged.get("recursive", True))
        merged["date_columns"] = list(merged.get("date_columns") or [])
        merged["file_patterns"] = list(merged.get("file_patterns") or ["*.csv", "*.parquet", "*.json"])
        merged["depends_on"] = list(merged.get("depends_on") or [])
        return merged

    def _resolve_path(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else self.root_dir / path

    def _rule_files(self, rule: dict[str, Any]) -> list[Path]:
        if not rule.get("path"):
            return []
        base = self._resolve_path(rule.get("path", ""))
        if base.is_file():
            return [base] if base.suffix.lower() in SUPPORTED_EXTENSIONS else []
        if not base.exists() or not base.is_dir():
            return []

        files: list[Path] = []
        for pattern in rule.get("file_patterns", []):
            iterator = base.rglob(pattern) if rule.get("recursive", True) else base.glob(pattern)
            files.extend(path for path in iterator if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
        return sorted(set(files))

    def _matching_rules(self, category: str | None = None, source_name: str | None = None) -> list[dict[str, Any]]:
        category_norm = (category or "").lower().replace("\\", "/")
        source_norm = (source_name or "").lower()
        rules = self.rules
        if category_norm:
            rules = [
                rule
                for rule in rules
                if category_norm in str(rule.get("category", "")).lower().replace("\\", "/")
                or category_norm in str(rule.get("name", "")).lower()
            ]
        if source_norm:
            rules = [rule for rule in rules if source_norm == str(rule.get("name", "")).lower()]
        return rules

    def get_latest_raw_date(self, category: str = "") -> date | None:
        rules = [
            rule
            for rule in self._matching_rules(category=category)
            if str(rule.get("category", "")).lower().startswith("raw")
        ]
        latest = self._latest_from_rules(rules)
        if latest:
            return latest

        fallback = self.data_lake / "raw" / category if category else self.data_lake / "raw"
        return self._latest_from_directory(fallback)

    def get_latest_metrics_date(self) -> date | None:
        rules = [
            rule
            for rule in self.rules
            if "metrics" in str(rule.get("category", "")).lower()
        ]
        if not rules:
            rules = [
                rule
                for rule in self.rules
                if "processed" in str(rule.get("category", "")).lower()
            ]
        latest = self._latest_from_rules(rules)
        if latest:
            return latest
        return self._latest_from_directory(self.data_lake / "processed" / "metrics")

    def check_data_freshness(self, threshold_days: int = 2) -> dict[str, Any]:
        sources = self.scan_sources(threshold_days=threshold_days)
        counts = {"healthy": 0, "warning": 0, "critical": 0}
        for source in sources:
            counts[source["status"]] = counts.get(source["status"], 0) + 1

        if counts.get("critical", 0):
            overall = "critical"
        elif counts.get("warning", 0):
            overall = "warning"
        else:
            overall = "healthy"

        return {
            "as_of": self.as_of.isoformat(),
            "overall_status": overall,
            "summary": {
                "source_count": len(sources),
                **counts,
            },
            "sources": sources,
        }

    def detect_gaps(
        self,
        start_date: date | str,
        end_date: date | str,
        source_name: str | None = None,
        category: str | None = None,
        frequency: str | None = None,
    ) -> list[date]:
        start = parse_date_value(start_date)
        end = parse_date_value(end_date)
        if start is None or end is None:
            return []
        if start > end:
            start, end = end, start

        rules = self._matching_rules(category=category, source_name=source_name)
        if not rules and source_name is None and category is None:
            rules = self._matching_rules(source_name="market_data")
        observed: set[date] = set()
        selected_frequency = frequency
        for rule in rules:
            selected_frequency = selected_frequency or str(rule.get("frequency") or "daily")
            observed.update(self._collect_dates_for_rule(rule))

        expected = self._expected_dates(start, end, selected_frequency or "business_daily")
        return [value for value in expected if value not in observed]

    def scan_sources(self, threshold_days: int = 2) -> list[dict[str, Any]]:
        self._status_cache = {}
        statuses = [self._scan_rule_cached(rule, threshold_days=threshold_days) for rule in self.rules]
        by_name = {status["name"]: status for status in statuses}

        for rule, status in zip(self.rules, statuses):
            reference_name = rule.get("reference_source")
            if not reference_name:
                continue
            reference = by_name.get(str(reference_name))
            if not reference:
                continue
            latest = parse_date_value(status.get("latest_data_date"))
            reference_latest = parse_date_value(reference.get("latest_data_date"))
            if latest is None or reference_latest is None:
                continue
            lag_days = (reference_latest - latest).days
            max_lag_days = int(rule.get("max_lag_days", status["warning_days"]))
            if lag_days > max_lag_days:
                status["reference_lag_days"] = lag_days
                status["status_reason"] += f"; lags {reference_name} by {lag_days} days"
                if lag_days > status["critical_days"]:
                    status["status"] = "critical"
                elif status["status"] == "healthy":
                    status["status"] = "warning"

        return statuses

    def _scan_rule_cached(self, rule: dict[str, Any], threshold_days: int) -> dict[str, Any]:
        name = str(rule.get("name", ""))
        if name in self._status_cache:
            return deepcopy(self._status_cache[name])
        status = self._scan_rule(rule, threshold_days=threshold_days)
        self._status_cache[name] = deepcopy(status)
        return status

    def build_timeline(self, days: int = 30, source_name: str | None = None) -> list[dict[str, Any]]:
        start = self.as_of - timedelta(days=days - 1)
        rows: list[dict[str, Any]] = []
        for rule in self._matching_rules(source_name=source_name):
            if str(rule.get("type", "")).lower() == "tool_metrics":
                continue
            observed = self._collect_dates_for_rule(rule)
            expected = self._expected_dates(start, self.as_of, str(rule.get("frequency") or "daily"))
            for value in expected:
                rows.append(
                    {
                        "source": rule["name"],
                        "category": rule["category"],
                        "date": value.isoformat(),
                        "has_data": value in observed,
                    }
                )
        return rows

    def export_report(self, output_path: str | Path, fmt: str = "json") -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        report = self.check_data_freshness()
        fmt = fmt.lower()
        if fmt == "json":
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        elif fmt == "csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                fieldnames = [
                    "name",
                    "category",
                    "status",
                    "latest_data_date",
                    "freshness_days",
                    "latest_file",
                    "file_count",
                    "warning_days",
                    "critical_days",
                    "tool",
                    "dependencies",
                    "cache_data_date",
                    "cache_status",
                    "status_reason",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in report["sources"]:
                    writer.writerow({key: row.get(key, "") for key in fieldnames})
        else:
            raise ValueError("fmt must be 'json' or 'csv'")
        return path

    def _latest_from_rules(self, rules: Iterable[dict[str, Any]]) -> date | None:
        dates: list[date] = []
        for rule in rules:
            status = self._scan_rule(rule, threshold_days=int(rule.get("warning_days", 2)))
            parsed = parse_date_value(status.get("latest_data_date"))
            if parsed:
                dates.append(parsed)
        return max(dates) if dates else None

    def _latest_from_directory(self, directory: Path) -> date | None:
        if not directory.exists():
            return None
        dates = []
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                record = self._file_record(path, {})
                if record.data_date:
                    dates.append(record.data_date)
        return max(dates) if dates else None

    def _scan_rule(self, rule: dict[str, Any], threshold_days: int) -> dict[str, Any]:
        if str(rule.get("type", "")).lower() == "tool_metrics":
            return self._scan_tool_metrics_rule(rule, threshold_days)

        files = self._rule_files(rule)
        records = [self._file_record(path, rule) for path in files]
        dated = [record for record in records if record.data_date is not None]
        latest_record = max(dated, key=lambda record: record.data_date) if dated else None
        warning_days = int(rule.get("warning_days", threshold_days))
        critical_days = int(rule.get("critical_days", max(warning_days + 1, threshold_days * 3)))

        if latest_record is None:
            return {
                "name": rule["name"],
                "category": rule["category"],
                "path": str(self._resolve_path(rule.get("path", ""))),
                "status": "critical",
                "status_reason": "no supported files or no date could be detected",
                "latest_data_date": None,
                "latest_file": None,
                "latest_file_mtime": None,
                "date_source": None,
                "freshness_days": None,
                "warning_days": warning_days,
                "critical_days": critical_days,
                "file_count": len(files),
                "errors": [record.error for record in records if record.error],
            }

        freshness_days = (self.as_of - latest_record.data_date).days
        status, reason = self._status_for_age(freshness_days, warning_days, critical_days)
        return {
            "name": rule["name"],
            "category": rule["category"],
            "path": str(self._resolve_path(rule.get("path", ""))),
            "status": status,
            "status_reason": reason,
            "latest_data_date": latest_record.data_date.isoformat(),
            "latest_file": str(latest_record.path),
            "latest_file_mtime": latest_record.mtime.isoformat(timespec="seconds"),
            "date_source": latest_record.date_source,
            "freshness_days": freshness_days,
            "warning_days": warning_days,
            "critical_days": critical_days,
            "file_count": len(files),
            "errors": [record.error for record in records if record.error],
        }

    def _scan_tool_metrics_rule(self, rule: dict[str, Any], threshold_days: int) -> dict[str, Any]:
        warning_days = int(rule.get("warning_days", threshold_days))
        critical_days = int(rule.get("critical_days", max(warning_days + 1, threshold_days * 3)))
        dependency_names = [str(name) for name in rule.get("depends_on", [])]
        dependency_statuses: list[dict[str, Any]] = []
        missing_dependencies: list[str] = []

        for dep_name in dependency_names:
            dep_rule = self.rule_by_name.get(dep_name)
            if dep_rule is None:
                missing_dependencies.append(dep_name)
                continue
            dependency_statuses.append(self._scan_rule_cached(dep_rule, threshold_days))

        dep_dates = []
        for dep_status in dependency_statuses:
            parsed = parse_date_value(dep_status.get("latest_data_date"))
            if parsed is not None:
                dep_dates.append(parsed)

        latest_metric_date = min(dep_dates) if dep_dates else None
        cache_info = self._latest_tool_cache(rule)

        if latest_metric_date is None:
            status = "critical"
            reason = "no dependency date could be detected"
            if missing_dependencies:
                reason += f"; missing dependencies: {', '.join(missing_dependencies)}"
            freshness_days = None
        else:
            freshness_days = (self.as_of - latest_metric_date).days
            status, reason = self._status_for_age(freshness_days, warning_days, critical_days)

        rank = {"healthy": 0, "warning": 1, "critical": 2}
        worst_dependency = None
        for dep_status in dependency_statuses:
            dep_rank = rank.get(str(dep_status.get("status")), 2)
            if worst_dependency is None or dep_rank > worst_dependency[0]:
                worst_dependency = (dep_rank, str(dep_status.get("status")), str(dep_status.get("name")))

        if worst_dependency is not None and worst_dependency[0] > rank.get(status, 0):
            status = worst_dependency[1]
            reason += f"; dependency {worst_dependency[2]} is {worst_dependency[1]}"

        latest_file = cache_info.get("path") or self._first_dependency_file(dependency_statuses)
        date_source = "derived_from_dependencies"
        if cache_info.get("data_date"):
            date_source += "+cache"

        return {
            "name": rule["name"],
            "category": rule["category"],
            "path": str(self.data_lake / "daily_cache"),
            "status": status,
            "status_reason": reason,
            "latest_data_date": latest_metric_date.isoformat() if latest_metric_date else None,
            "latest_file": latest_file,
            "latest_file_mtime": cache_info.get("mtime"),
            "date_source": date_source,
            "freshness_days": freshness_days,
            "warning_days": warning_days,
            "critical_days": critical_days,
            "file_count": int(cache_info.get("file_count", 0)),
            "tool": rule.get("tool", rule["name"]),
            "dependencies": ", ".join(dependency_names),
            "cache_namespace": rule.get("cache_namespace"),
            "cache_data_date": cache_info.get("data_date"),
            "cache_status": self._cache_status(cache_info.get("data_date"), latest_metric_date),
            "errors": [f"missing dependency: {name}" for name in missing_dependencies],
        }

    def _first_dependency_file(self, dependency_statuses: list[dict[str, Any]]) -> str | None:
        for status in dependency_statuses:
            if status.get("latest_file"):
                return str(status["latest_file"])
        return None

    def _latest_tool_cache(self, rule: dict[str, Any]) -> dict[str, Any]:
        namespace = rule.get("cache_namespace")
        if not namespace:
            return {"file_count": 0}

        cache_dir = self.data_lake / "daily_cache"
        if not cache_dir.exists():
            return {"file_count": 0}

        files = [
            path
            for path in cache_dir.glob(f"{namespace}*")
            if path.is_file() and path.suffix.lower() in {".pkl", ".csv"}
        ]
        if not files:
            return {"file_count": 0}

        latest_path = max(files, key=lambda path: path.stat().st_mtime)
        data_date = self._cache_data_date(latest_path)
        mtime = datetime.fromtimestamp(latest_path.stat().st_mtime)
        return {
            "path": str(latest_path),
            "data_date": data_date.isoformat() if data_date else None,
            "mtime": mtime.isoformat(timespec="seconds"),
            "file_count": len(files),
        }

    def _cache_data_date(self, path: Path) -> date | None:
        if path.suffix.lower() == ".pkl":
            try:
                with path.open("rb") as handle:
                    obj = pickle.load(handle)
                return parse_date_value(obj.get("data_date"))
            except Exception:
                return None

        if path.suffix.lower() == ".csv":
            try:
                import pandas as pd

                header = pd.read_csv(path, nrows=0)
                column = self._choose_date_column(list(header.columns), ["data_date", "cache_date", "date", "DATE"])
                if column is None:
                    return None
                series = pd.read_csv(path, usecols=[column], dtype=str)[column]
                return latest_date(series.dropna().tolist())
            except Exception:
                return None

        return None

    def _cache_status(self, cache_data_date: str | None, latest_metric_date: date | None) -> str:
        parsed_cache = parse_date_value(cache_data_date)
        if parsed_cache is None:
            return "missing"
        if latest_metric_date is None:
            return "available"
        if parsed_cache >= latest_metric_date:
            return "current"
        return "stale"

    def _status_for_age(self, age_days: int, warning_days: int, critical_days: int) -> tuple[str, str]:
        if age_days < 0:
            return "warning", f"latest date is {-age_days} days in the future"
        if age_days <= warning_days:
            return "healthy", f"fresh: {age_days} days old"
        if age_days <= critical_days:
            return "warning", f"stale: {age_days} days old"
        return "critical", f"critical: {age_days} days old"

    def _file_record(self, path: Path, rule: dict[str, Any]) -> FileRecord:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        filename_dates = extract_dates_from_text(path.stem)
        if filename_dates:
            return FileRecord(path=path, data_date=max(filename_dates), date_source="filename", mtime=mtime)

        try:
            content_date = self._latest_content_date(path, rule)
            if content_date:
                return FileRecord(path=path, data_date=content_date, date_source="content", mtime=mtime)
        except Exception as exc:
            return FileRecord(
                path=path,
                data_date=mtime.date(),
                date_source="mtime",
                mtime=mtime,
                error=f"{path.name}: {exc}",
            )

        return FileRecord(path=path, data_date=mtime.date(), date_source="mtime", mtime=mtime)

    def _latest_content_date(self, path: Path, rule: dict[str, Any]) -> date | None:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._latest_date_in_csv(path, rule.get("date_columns") or [])
        if suffix == ".parquet":
            return self._latest_date_in_parquet(path, rule.get("date_columns") or [])
        if suffix == ".json":
            return self._latest_date_in_json(path)
        return None

    def _latest_date_in_csv(self, path: Path, date_columns: list[str]) -> date | None:
        try:
            import pandas as pd

            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    header = pd.read_csv(path, nrows=0, encoding=encoding)
                    columns = list(header.columns)
                    column = self._choose_date_column(columns, date_columns)
                    if column is None:
                        return None
                    series = pd.read_csv(path, usecols=[column], encoding=encoding, dtype=str)[column]
                    return latest_date(series.dropna().tolist())
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass

        return self._latest_date_in_csv_fallback(path, date_columns)

    def _latest_date_in_csv_fallback(self, path: Path, date_columns: list[str]) -> date | None:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                return None
            column = self._choose_date_column(header, date_columns)
            if column is None:
                return None
            index = header.index(column)
            values = [row[index] for row in reader if len(row) > index]
        return latest_date(values)

    def _latest_date_in_parquet(self, path: Path, date_columns: list[str]) -> date | None:
        import pandas as pd

        frame = pd.read_parquet(path)
        column = self._choose_date_column(list(frame.columns), date_columns)
        if column is None:
            return None
        return latest_date(frame[column].dropna().tolist())

    def _latest_date_in_json(self, path: Path) -> date | None:
        data = json.loads(path.read_text(encoding="utf-8"))
        values: list[object] = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if any(token in str(key).lower() for token in ("date", "time", "period")):
                        values.append(child)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, (str, int, float)):
                values.append(value)

        walk(data)
        return latest_date(values)

    def _choose_date_column(self, columns: list[str], preferred: list[str]) -> str | None:
        if not columns:
            return None
        lower_map = {str(column).lower(): column for column in columns}
        for name in preferred:
            column = lower_map.get(str(name).lower())
            if column is not None:
                return column

        for column in columns:
            normalized = str(column).strip().lower()
            if any(token in normalized for token in ("date", "time", "period", "ddmmyyyy")):
                return column

        return columns[0]

    def _collect_dates_for_rule(self, rule: dict[str, Any]) -> set[date]:
        dates: set[date] = set()
        for path in self._rule_files(rule):
            filename_dates = extract_dates_from_text(path.stem)
            dates.update(filename_dates)
            try:
                content_dates = self._content_dates(path, rule)
                dates.update(content_dates)
            except Exception:
                record = self._file_record(path, rule)
                if record.data_date:
                    dates.add(record.data_date)
        return dates

    def _content_dates(self, path: Path, rule: dict[str, Any]) -> set[date]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            values = self._date_values_in_csv(path, rule.get("date_columns") or [])
        elif suffix == ".parquet":
            values = self._date_values_in_parquet(path, rule.get("date_columns") or [])
        elif suffix == ".json":
            value = self._latest_date_in_json(path)
            values = [value] if value else []
        else:
            values = []
        return {parsed for parsed in (parse_date_value(value) for value in values) if parsed is not None}

    def _date_values_in_csv(self, path: Path, date_columns: list[str]) -> list[object]:
        try:
            import pandas as pd

            header = pd.read_csv(path, nrows=0, encoding="utf-8-sig")
            column = self._choose_date_column(list(header.columns), date_columns)
            if column is None:
                return []
            series = pd.read_csv(path, usecols=[column], encoding="utf-8-sig", dtype=str)[column]
            return series.dropna().tolist()
        except Exception:
            with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
                reader = csv.reader(handle)
                try:
                    header = next(reader)
                except StopIteration:
                    return []
                column = self._choose_date_column(header, date_columns)
                if column is None:
                    return []
                index = header.index(column)
                return [row[index] for row in reader if len(row) > index]

    def _date_values_in_parquet(self, path: Path, date_columns: list[str]) -> list[object]:
        import pandas as pd

        frame = pd.read_parquet(path)
        column = self._choose_date_column(list(frame.columns), date_columns)
        if column is None:
            return []
        return frame[column].dropna().tolist()

    def _expected_dates(self, start: date, end: date, frequency: str) -> list[date]:
        values: list[date] = []
        current = start
        frequency = frequency.lower()
        while current <= end:
            include = True
            if frequency in {"business_daily", "business"}:
                include = current.weekday() < 5
            elif frequency == "weekly":
                include = current.weekday() == start.weekday()
            elif frequency == "monthly":
                include = current.day == start.day
            elif frequency == "quarterly":
                include = (current.month, current.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}
            if include:
                values.append(current)
            current += timedelta(days=1)
        return values


def format_cli_report(report: dict[str, Any]) -> str:
    lines = [
        f"Data Health Report - as of {report['as_of']}",
        f"Overall status: {report['overall_status'].upper()}",
        "",
        "Sources:",
    ]
    for source in report["sources"]:
        latest = source.get("latest_data_date") or "n/a"
        age = source.get("freshness_days")
        age_text = "n/a" if age is None else f"{age}d"
        lines.append(
            f"- {source['name']}: {source['status'].upper()} | latest={latest} | age={age_text} | files={source['file_count']}"
        )
    return "\n".join(lines)
