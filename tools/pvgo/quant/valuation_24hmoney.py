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

TABLE_NAME = "vnindex_valuation_history"
DEFAULT_FLOOR_CODE = "10"
DEFAULT_INDEX_CODE = "VNINDEX"
DEFAULT_RANGE_TYPE = "5"
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

    def run(self, *, output_dir: Path = DEFAULT_OUTPUT_DIR, dry_run: bool = False) -> dict[str, Any]:
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
        tagged = frame.copy()
        tagged["scraped_at"] = pd.Timestamp.now(tz=VN_TZ).isoformat()
        tagged["scrape_run_id"] = self.run_id
        tagged["date"] = pd.to_datetime(tagged["date"]).dt.strftime("%Y-%m-%d")

        column_order = CORE_COLUMNS + ["scrape_run_id", "scraped_at"]
        csv_path = output_dir / f"{TABLE_NAME}.csv"

        if dry_run:
            print(tagged[column_order].to_string(index=False))
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            if csv_path.exists():
                try:
                    existing_df = pd.read_csv(csv_path)
                    existing_df["date"] = pd.to_datetime(existing_df["date"]).dt.strftime("%Y-%m-%d")
                    combined = pd.concat([existing_df, tagged], ignore_index=True)
                except Exception as exc:
                    print(f"Warning: could not read existing CSV at {csv_path}: {exc}")
                    combined = tagged
            else:
                combined = tagged

            for col in column_order:
                if col not in combined:
                    combined[col] = None
            combined = (
                combined[column_order]
                .drop_duplicates(subset=["date", "index_code"], keep="last")
                .sort_values(["date", "index_code"])
                .reset_index(drop=True)
            )
            combined.to_csv(csv_path, index=False, encoding="utf-8")
            stats["tables_written"] = 1
            stats["rows_written"] = int(len(combined))
            stats["csv_path"] = str(csv_path)

        stats["elapsed_s"] = round(time.time() - started, 2)
        return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update PVGO VNINDEX valuation history")
    parser.add_argument("--floor-code", default=DEFAULT_FLOOR_CODE)
    parser.add_argument("--index-code", default=DEFAULT_INDEX_CODE)
    parser.add_argument("--range-type", default=DEFAULT_RANGE_TYPE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    scraper = Money24hVNIndexValuationScraper(
        floor_code=args.floor_code,
        index_code=args.index_code,
        range_type=args.range_type,
    )
    stats = scraper.run(output_dir=args.output_dir, dry_run=args.dry_run)
    print("DONE:", json.dumps(stats, default=str, indent=2))
    return 0 if stats["rows_ready"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

