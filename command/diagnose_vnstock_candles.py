"""So sánh nến OHLCV VCI/KBS mà không thay đổi dữ liệu dự án.

Ví dụ:
    python command/diagnose_vnstock_candles.py
    python command/diagnose_vnstock_candles.py --symbols VNINDEX FPT --intervals 1D 15m
    python command/diagnose_vnstock_candles.py --start 2026-07-23 --end 2026-07-25 --strict

Mã thoát:
    0: hai API trả nến hợp lệ về cấu trúc (có thể vẫn có cảnh báo)
    1: ít nhất một nguồn lỗi hoặc trả nến không hợp lệ
    2: dùng --strict và phát hiện cảnh báo/chênh lệch giữa hai nguồn
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SOURCES = ("VCI", "KBS")
DEFAULT_SYMBOLS = ("VNINDEX", "VN30", "FPT", "VN30F1M")
REQUIRED_COLUMNS = ("time", "open", "high", "low", "close", "volume")
OHLC_COLUMNS = ("open", "high", "low", "close")
DAILY_INTERVALS = frozenset({"1D", "1d", "D", "d", "daily"})
STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}


@dataclass
class SourceCheck:
    symbol: str
    source: str
    interval: str
    status: str
    api_ok: bool
    elapsed_seconds: float
    rows: int = 0
    first_time: str | None = None
    last_time: str | None = None
    missing_columns: list[str] = field(default_factory=list)
    invalid_time_rows: int = 0
    duplicate_time_rows: int = 0
    outside_requested_range_rows: int = 0
    null_ohlc_rows: int = 0
    invalid_ohlc_rows: int = 0
    negative_volume_rows: int = 0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_type: str | None = None
    error: str | None = None


@dataclass
class FieldComparison:
    mismatch_rows: int
    max_absolute_difference: float | None
    max_relative_difference: float | None


@dataclass
class SourceComparison:
    symbol: str
    interval: str
    common_rows: int
    vci_only_rows: int
    kbs_only_rows: int
    fields: dict[str, FieldComparison]

    @property
    def has_mismatch(self) -> bool:
        return (
            self.vci_only_rows > 0
            or self.kbs_only_rows > 0
            or any(item.mismatch_rows > 0 for item in self.fields.values())
        )


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _time_key(frame: pd.DataFrame, interval: str) -> pd.Series:
    parsed = pd.to_datetime(frame["time"], errors="coerce")
    if interval in DAILY_INTERVALS:
        return parsed.dt.normalize()
    return parsed


def _requested_bounds(
    start: str, end: str, interval: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    lower = pd.Timestamp(start)
    upper = pd.Timestamp(end)
    if interval in DAILY_INTERVALS:
        return lower.normalize(), upper.normalize()
    if len(end.strip()) == 10:
        upper = upper + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return lower, upper


def analyze_frame(
    frame: pd.DataFrame | None,
    *,
    symbol: str,
    source: str,
    interval: str,
    start: str,
    end: str,
    elapsed_seconds: float = 0.0,
) -> SourceCheck:
    check = SourceCheck(
        symbol=symbol,
        source=source,
        interval=interval,
        status="PASS",
        api_ok=True,
        elapsed_seconds=round(elapsed_seconds, 3),
    )
    if frame is None or frame.empty:
        check.status = "FAIL"
        check.issues.append("API không trả về nến")
        return check

    check.rows = len(frame)
    check.missing_columns = [
        col for col in REQUIRED_COLUMNS if col not in frame.columns
    ]
    if check.missing_columns:
        check.status = "FAIL"
        check.issues.append(f"thiếu cột: {', '.join(check.missing_columns)}")
        return check

    work = frame.loc[:, REQUIRED_COLUMNS].copy()
    times = _time_key(work, interval)
    check.invalid_time_rows = int(times.isna().sum())
    valid_times = times.dropna()
    if not valid_times.empty:
        check.first_time = valid_times.min().isoformat()
        check.last_time = valid_times.max().isoformat()
    check.duplicate_time_rows = int(times.duplicated(keep=False).sum())

    lower, upper = _requested_bounds(start, end, interval)
    check.outside_requested_range_rows = int(((times < lower) | (times > upper)).sum())

    for column in (*OHLC_COLUMNS, "volume"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    check.null_ohlc_rows = int(work.loc[:, OHLC_COLUMNS].isna().any(axis=1).sum())

    complete = work.loc[:, OHLC_COLUMNS].notna().all(axis=1)
    invalid_ohlc = complete & (
        (work["low"] > work[["open", "close"]].min(axis=1))
        | (work["high"] < work[["open", "close"]].max(axis=1))
        | (work["low"] > work["high"])
    )
    check.invalid_ohlc_rows = int(invalid_ohlc.sum())
    check.negative_volume_rows = int((work["volume"] < 0).fillna(False).sum())

    failures = {
        "timestamp không đọc được": check.invalid_time_rows,
        "timestamp trùng": check.duplicate_time_rows,
        "dòng có OHLC rỗng": check.null_ohlc_rows,
        "dòng vi phạm low <= open/close <= high": check.invalid_ohlc_rows,
        "dòng có volume âm": check.negative_volume_rows,
    }
    check.issues.extend(
        f"{label}: {count}" for label, count in failures.items() if count
    )
    if check.issues:
        check.status = "FAIL"

    if check.outside_requested_range_rows:
        check.warnings.append(
            f"nến nằm ngoài khoảng yêu cầu [{start}, {end}]: "
            f"{check.outside_requested_range_rows}"
        )
        if check.status == "PASS":
            check.status = "WARN"
    return check


def fetch_and_analyze(
    *, symbol: str, source: str, interval: str, start: str, end: str
) -> tuple[SourceCheck, pd.DataFrame | None]:
    started = time.perf_counter()
    try:
        from vnstock import Quote

        frame = Quote(symbol=symbol, source=source).history(
            start=start,
            end=end,
            interval=interval,
        )
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        return (
            SourceCheck(
                symbol=symbol,
                source=source,
                interval=interval,
                status="FAIL",
                api_ok=False,
                elapsed_seconds=elapsed,
                issues=["Lệnh gọi API phát sinh exception"],
                error_type=type(exc).__name__,
                error=str(exc),
            ),
            None,
        )

    elapsed = time.perf_counter() - started
    return (
        analyze_frame(
            frame,
            symbol=symbol,
            source=source,
            interval=interval,
            start=start,
            end=end,
            elapsed_seconds=elapsed,
        ),
        frame,
    )


def _comparison_frame(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    work = frame.loc[:, REQUIRED_COLUMNS].copy()
    work["time_key"] = _time_key(work, interval)
    work = work.dropna(subset=["time_key"]).drop_duplicates("time_key", keep="last")
    for column in (*OHLC_COLUMNS, "volume"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work.set_index("time_key").sort_index()


def compare_sources(
    vci: pd.DataFrame,
    kbs: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    price_rtol: float = 1e-6,
    volume_rtol: float = 0.01,
) -> SourceComparison:
    left = _comparison_frame(vci, interval)
    right = _comparison_frame(kbs, interval)
    common_index = left.index.intersection(right.index)
    fields: dict[str, FieldComparison] = {}

    for column in (*OHLC_COLUMNS, "volume"):
        left_values = left.loc[common_index, column].to_numpy(dtype=float)
        right_values = right.loc[common_index, column].to_numpy(dtype=float)
        tolerance = volume_rtol if column == "volume" else price_rtol
        equal = np.isclose(
            left_values,
            right_values,
            rtol=tolerance,
            atol=1e-9,
            equal_nan=True,
        )
        finite = np.isfinite(left_values) & np.isfinite(right_values)
        absolute = np.abs(left_values[finite] - right_values[finite])
        denominator = np.maximum(np.abs(right_values[finite]), 1e-12)
        relative = absolute / denominator
        fields[column] = FieldComparison(
            mismatch_rows=int((~equal).sum()),
            max_absolute_difference=float(absolute.max()) if absolute.size else None,
            max_relative_difference=float(relative.max()) if relative.size else None,
        )

    return SourceComparison(
        symbol=symbol,
        interval=interval,
        common_rows=len(common_index),
        vci_only_rows=len(left.index.difference(right.index)),
        kbs_only_rows=len(right.index.difference(left.index)),
        fields=fields,
    )


def _print_source_check(check: SourceCheck) -> None:
    print(
        f"[{check.status}] {check.symbol:<8} {check.interval:<4} {check.source}: "
        f"rows={check.rows}, first={check.first_time}, last={check.last_time}, "
        f"elapsed={check.elapsed_seconds:.3f}s"
    )
    for message in check.issues:
        print(f"  ERROR: {message}")
    for message in check.warnings:
        print(f"  WARN: {message}")
    if check.error:
        print(f"  EXCEPTION: {check.error_type}: {check.error}")


def _print_comparison(comparison: SourceComparison) -> None:
    mismatches = (
        ", ".join(
            f"{name}={details.mismatch_rows}"
            for name, details in comparison.fields.items()
            if details.mismatch_rows
        )
        or "none"
    )
    status = "WARN" if comparison.has_mismatch else "PASS"
    print(
        f"[{status}] {comparison.symbol:<8} {comparison.interval:<4} VCI vs KBS: "
        f"common={comparison.common_rows}, VCI-only={comparison.vci_only_rows}, "
        f"KBS-only={comparison.kbs_only_rows}, field mismatches: {mismatches}"
    )


def run_diagnostic(
    *,
    symbols: list[str],
    intervals: list[str],
    start: str,
    end: str,
    pause_seconds: float,
) -> dict[str, Any]:
    checks: list[SourceCheck] = []
    comparisons: list[SourceComparison] = []

    print(
        f"vnstock={_package_version('vnstock')} | range={start}..{end} | "
        f"symbols={','.join(symbols)} | intervals={','.join(intervals)}"
    )
    for symbol in symbols:
        for interval in intervals:
            frames: dict[str, pd.DataFrame] = {}
            for source in SOURCES:
                check, frame = fetch_and_analyze(
                    symbol=symbol,
                    source=source,
                    interval=interval,
                    start=start,
                    end=end,
                )
                checks.append(check)
                _print_source_check(check)
                if frame is not None and not frame.empty and not check.missing_columns:
                    frames[source] = frame
                if pause_seconds > 0:
                    time.sleep(pause_seconds)

            if all(source in frames for source in SOURCES):
                comparison = compare_sources(
                    frames["VCI"],
                    frames["KBS"],
                    symbol=symbol,
                    interval=interval,
                )
                comparisons.append(comparison)
                _print_comparison(comparison)

    source_summary: dict[str, str] = {}
    for source in SOURCES:
        source_checks = [item for item in checks if item.source == source]
        source_summary[source] = max(
            (item.status for item in source_checks),
            key=lambda status: STATUS_RANK[status],
            default="FAIL",
        )

    print(
        "\nKết luận theo nguồn: "
        + ", ".join(f"{k}={v}" for k, v in source_summary.items())
    )
    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").isoformat(),
        "vnstock_version": _package_version("vnstock"),
        "request": {
            "symbols": symbols,
            "intervals": intervals,
            "start": start,
            "end": end,
        },
        "source_summary": source_summary,
        "checks": [asdict(item) for item in checks],
        "comparisons": [asdict(item) for item in comparisons],
    }


def _parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(
        description="Chẩn đoán live nến OHLCV VCI/KBS qua vnstock."
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--intervals", nargs="+", default=["1D"])
    parser.add_argument(
        "--start",
        default=(today - timedelta(days=10)).isoformat(),
        help="Ngày/thời gian bắt đầu truyền vào Quote.history.",
    )
    parser.add_argument(
        "--end",
        default=today.isoformat(),
        help="Ngày/thời gian kết thúc truyền vào Quote.history.",
    )
    parser.add_argument(
        "--pause", type=float, default=0.5, help="Độ trễ giữa các lệnh API."
    )
    parser.add_argument("--json-output", type=Path, help="Đường dẫn JSON tùy chọn.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Trả mã 2 nếu có cảnh báo biên ngày hoặc VCI/KBS không khớp.",
    )
    return parser.parse_args()


def main() -> int:
    _configure_utf8_console()
    args = _parse_args()
    report = run_diagnostic(
        symbols=[str(symbol).strip().upper() for symbol in args.symbols],
        intervals=[str(interval).strip() for interval in args.intervals],
        start=args.start,
        end=args.end,
        pause_seconds=max(0.0, args.pause),
    )
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report: {args.json_output}")

    if any(check["status"] == "FAIL" for check in report["checks"]):
        return 1
    if args.strict and (
        any(check["status"] == "WARN" for check in report["checks"])
        or any(
            comparison["vci_only_rows"]
            or comparison["kbs_only_rows"]
            or any(
                details["mismatch_rows"] for details in comparison["fields"].values()
            )
            for comparison in report["comparisons"]
        )
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
