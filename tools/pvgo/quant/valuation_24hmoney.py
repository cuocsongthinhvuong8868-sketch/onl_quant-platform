"""24hmoney VNINDEX P/E and P/B valuation history scraper.

This module fetches the key-statistic history used by the PVGO model. It is
data-only and does not call any AI service.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from config import DATA_LAKE
from tools.pvgo.freshness import (
    DEFAULT_MARKET_DATA_PATH,
    evaluate_pvgo_freshness,
    load_market_dates,
)

TABLE_NAME = "vnindex_valuation_history"
DEFAULT_FLOOR_CODE = "10"
DEFAULT_INDEX_CODE = "VNINDEX"
DEFAULT_RANGE_TYPE = "5"
# 24hmoney publishes the completed valuation snapshot on a T+1 schedule.  The
# updater therefore accepts the previous observed market session by default,
# while PVGO report consumers keep their stricter zero-lag freshness policy.
DEFAULT_UPDATE_MAX_SESSION_LAG = 1
PAGE_URL = "https://24hmoney.vn/indices/vn-index"
API_URL = "https://api-finance-t19.24hmoney.vn/v1/ios/indices/key-statistic-history"
SOURCE_NAME = "24hmoney:key-statistic-history"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_OUTPUT_DIR = DATA_LAKE / "pvgo"

CORE_COLUMNS = [
    "date",
    "index_code",
    "floor_code",
    "close",
    "pe",
    "pb",
    "range_type",
    "source_url",
    "source",
]
KEY_COLUMNS = ["date", "index_code"]
METADATA_COLUMNS = ["scrape_run_id", "scraped_at"]
NUMERIC_COLUMNS = ["close", "pe", "pb"]
TEXT_COLUMNS = ["index_code", "floor_code", "range_type", "source_url", "source"]


def _parse_trading_date(value: Any) -> dt.date | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    seconds = float(numeric)
    if seconds > 10_000_000_000:
        seconds /= 1000.0
    return dt.datetime.fromtimestamp(seconds, tz=VN_TZ).date()


def _number(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return float("nan")
    return float(numeric)


def _source_url(floor_code: str, range_type: str) -> str:
    return f"{API_URL}?floor_code={floor_code}&type={range_type}"


def normalize_key_statistic_history(
    rows: list[dict[str, Any]] | pd.DataFrame | None,
    *,
    floor_code: str = DEFAULT_FLOOR_CODE,
    index_code: str = DEFAULT_INDEX_CODE,
    range_type: str = DEFAULT_RANGE_TYPE,
) -> pd.DataFrame:
    """Normalize 24hmoney API rows into the PVGO valuation schema."""
    if rows is None:
        return pd.DataFrame(columns=CORE_COLUMNS)
    data = pd.DataFrame(rows)
    if data.empty or "trading_date" not in data:
        return pd.DataFrame(columns=CORE_COLUMNS)

    output_rows: list[dict[str, Any]] = []
    source_url = _source_url(floor_code, range_type)
    for item in data.to_dict("records"):
        trade_date = _parse_trading_date(item.get("trading_date"))
        if trade_date is None:
            continue
        output_rows.append(
            {
                "date": trade_date,
                "index_code": index_code,
                "floor_code": str(floor_code),
                "close": _number(item.get("index")),
                "pe": _number(item.get("pe")),
                "pb": _number(item.get("pb")),
                "range_type": str(range_type),
                "source_url": source_url,
                "source": SOURCE_NAME,
            }
        )

    if not output_rows:
        return pd.DataFrame(columns=CORE_COLUMNS)

    df = (
        pd.DataFrame(output_rows)[CORE_COLUMNS]
        .drop_duplicates(["date", "index_code"], keep="last")
        .sort_values(["date", "index_code"])
        .reset_index(drop=True)
    )
    df.loc[df["pe"] <= 0, "pe"] = None
    df.loc[df["pb"] <= 0, "pb"] = None
    df["pe"] = df["pe"].interpolate(method="linear").ffill().bfill()
    df["pb"] = df["pb"].interpolate(method="linear").ffill().bfill()
    return df


def _canonical_core(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize persisted values so unchanged API rows compare idempotently."""
    normalized = frame.copy()
    for column in CORE_COLUMNS:
        if column not in normalized:
            normalized[column] = None

    normalized["date"] = pd.to_datetime(
        normalized["date"],
        format="mixed",
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    for column in TEXT_COLUMNS:
        normalized[column] = normalized[column].fillna("").astype(str)
    for column in ("floor_code", "range_type"):
        normalized[column] = normalized[column].str.replace(r"\.0$", "", regex=True)
    for column in NUMERIC_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").round(10)

    return normalized[CORE_COLUMNS]


def _sanitize_existing_history(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop malformed/duplicate persisted rows and restore canonical field types."""
    column_order = CORE_COLUMNS + METADATA_COLUMNS
    normalized = frame.copy()
    for column in column_order:
        if column not in normalized:
            normalized[column] = None

    normalized[CORE_COLUMNS] = _canonical_core(normalized)
    valid_keys = normalized["date"].notna() & normalized["index_code"].ne("")
    invalid_rows = int((~valid_keys).sum())
    normalized = normalized.loc[valid_keys, column_order].copy()

    duplicates = normalized.duplicated(KEY_COLUMNS, keep="last")
    duplicate_rows = int(duplicates.sum())
    normalized = normalized.loc[~duplicates].reset_index(drop=True)
    return normalized, invalid_rows + duplicate_rows


def _changed_incoming_rows(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    """Return only new or source-revised rows plus added/updated counts."""
    incoming_core = _canonical_core(incoming).dropna(subset=KEY_COLUMNS)
    incoming_core = incoming_core.drop_duplicates(KEY_COLUMNS, keep="last")
    if existing.empty:
        return incoming_core.reset_index(drop=True), int(len(incoming_core)), 0

    existing_core = _canonical_core(existing).dropna(subset=KEY_COLUMNS)
    existing_core = existing_core.drop_duplicates(KEY_COLUMNS, keep="last")
    incoming_indexed = incoming_core.set_index(KEY_COLUMNS)
    existing_indexed = existing_core.set_index(KEY_COLUMNS)

    is_new = ~incoming_indexed.index.isin(existing_indexed.index)
    changed = pd.Series(is_new, index=incoming_indexed.index, dtype=bool)
    common = incoming_indexed.index[~is_new]
    if len(common):
        left = incoming_indexed.loc[common]
        right = existing_indexed.reindex(common)
        equal_cells = left.eq(right) | (left.isna() & right.isna())
        changed.loc[common] = ~equal_cells.all(axis=1)

    changed_rows = incoming_indexed.loc[changed].reset_index()
    rows_added = int(is_new.sum())
    rows_updated = int(changed.sum()) - rows_added
    return changed_rows[CORE_COLUMNS], rows_added, rows_updated


class Money24hVNIndexValuationScraper:
    name = "vnindex_valuation_24hmoney"
    source_url = PAGE_URL
    rate_limit_seconds = 1.0

    def __init__(
        self,
        *,
        floor_code: str = DEFAULT_FLOOR_CODE,
        index_code: str = DEFAULT_INDEX_CODE,
        range_type: str = DEFAULT_RANGE_TYPE,
    ) -> None:
        self.floor_code = floor_code
        self.index_code = index_code
        self.range_type = range_type
        self.run_id = uuid.uuid4().hex

    def get_json(self, url: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
        if self.rate_limit_seconds > 0:
            time.sleep(self.rate_limit_seconds)
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_history(self) -> list[dict[str, Any]]:
        payload = self.get_json(
            API_URL,
            params={"floor_code": self.floor_code, "type": self.range_type},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://24hmoney.vn",
                "Referer": PAGE_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        return data if isinstance(data, list) else []

    def scrape(self) -> pd.DataFrame:
        return normalize_key_statistic_history(
            self.fetch_history(),
            floor_code=self.floor_code,
            index_code=self.index_code,
            range_type=self.range_type,
        )

    def run(
        self,
        *,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        dry_run: bool = False,
        market_data_path: Path = DEFAULT_MARKET_DATA_PATH,
        max_session_lag: int = DEFAULT_UPDATE_MAX_SESSION_LAG,
    ) -> dict[str, Any]:
        started = time.time()
        frame = self.scrape()
        stats: dict[str, Any] = {
            "tables_written": 0,
            "rows_ready": int(len(frame)),
            "floor_code": self.floor_code,
            "index_code": self.index_code,
            "range_type": self.range_type,
        }
        if frame.empty:
            stats["elapsed_s"] = round(time.time() - started, 2)
            return stats

        stats["earliest_date"] = str(frame["date"].min())
        stats["latest_date"] = str(frame["date"].max())
        freshness = evaluate_pvgo_freshness(
            frame["date"].max(),
            load_market_dates(market_data_path),
            max_session_lag=max_session_lag,
        )
        stats.update(
            {
                "freshness_status": freshness["status"],
                "market_latest_date": freshness["market_date"],
                "session_lag": freshness["session_lag"],
                "max_session_lag": freshness["max_session_lag"],
            }
        )

        incoming = _canonical_core(frame)
        column_order = CORE_COLUMNS + METADATA_COLUMNS
        csv_path = output_dir / f"{TABLE_NAME}.csv"
        existing_df = pd.DataFrame(columns=column_order)
        history_rows_repaired = 0
        if csv_path.exists():
            try:
                existing_df = pd.read_csv(csv_path)
                existing_df, history_rows_repaired = _sanitize_existing_history(existing_df)
            except Exception as exc:
                print(f"Warning: could not read existing CSV at {csv_path}: {exc}")

        changed_rows, rows_added, rows_updated = _changed_incoming_rows(existing_df, incoming)
        stats.update(
            {
                "rows_added": rows_added,
                "rows_updated": rows_updated,
                "rows_unchanged": int(len(incoming) - len(changed_rows)),
                "data_changed": bool(len(changed_rows)),
                "history_rows_repaired": history_rows_repaired,
            }
        )

        if dry_run:
            print(incoming[CORE_COLUMNS].to_string(index=False))
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            if len(changed_rows) or history_rows_repaired:
                tagged = changed_rows.copy()
                tagged["scrape_run_id"] = self.run_id
                tagged["scraped_at"] = pd.Timestamp.now(tz=VN_TZ).isoformat()
                combined = pd.concat([existing_df, tagged], ignore_index=True)
                for column in column_order:
                    if column not in combined:
                        combined[column] = None
                combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                combined = (
                    combined[column_order]
                    .dropna(subset=KEY_COLUMNS)
                    .drop_duplicates(subset=KEY_COLUMNS, keep="last")
                    .sort_values(KEY_COLUMNS)
                    .reset_index(drop=True)
                )
                combined.to_csv(csv_path, index=False, encoding="utf-8")
                stats["tables_written"] = 1
                stats["rows_written"] = int(len(combined))
            else:
                stats["rows_written"] = int(len(existing_df))
            stats["csv_path"] = str(csv_path)

        stats["elapsed_s"] = round(time.time() - started, 2)
        return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update PVGO VNINDEX valuation history")
    parser.add_argument("--floor-code", default=DEFAULT_FLOOR_CODE)
    parser.add_argument("--index-code", default=DEFAULT_INDEX_CODE)
    parser.add_argument("--range-type", default=DEFAULT_RANGE_TYPE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--market-data-path", type=Path, default=DEFAULT_MARKET_DATA_PATH)
    parser.add_argument(
        "--max-session-lag",
        type=int,
        default=DEFAULT_UPDATE_MAX_SESSION_LAG,
        help="Maximum accepted lag in observed market sessions (default: 1 for the T+1 feed).",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Exit successfully even when PVGO is more than max-session-lag market sessions behind.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    scraper = Money24hVNIndexValuationScraper(
        floor_code=args.floor_code,
        index_code=args.index_code,
        range_type=args.range_type,
    )
    stats = scraper.run(
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        market_data_path=args.market_data_path,
        max_session_lag=args.max_session_lag,
    )
    print("DONE:", json.dumps(stats, default=str, indent=2))
    if stats["rows_ready"] <= 0:
        return 1
    if stats.get("freshness_status") == "STALE" and not args.allow_stale:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
