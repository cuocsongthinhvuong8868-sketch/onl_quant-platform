import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .config import CANONICAL_MAPPINGS, FINANCIAL_SECTORS, RAW_JSON_DIR


@dataclass(frozen=True)
class LoadedData:
    metadata: pd.DataFrame
    statement_long: pd.DataFrame
    canonical: pd.DataFrame


def normalize_key(value: str) -> str:
    text = (value or "").split("\n")[0].strip().lower()
    text = re.sub(r"\s*\(before\s+\d{4}\)\s*", " ", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_label(value: str) -> str:
    return (value or "").split("\n")[0].strip()


def parse_period(value: str) -> tuple[str | None, int | None, int | None, int | None]:
    match = re.search(r"Q([1-4])\s*(20\d{2})", str(value or ""), flags=re.I)
    if not match:
        return None, None, None, None
    quarter = int(match.group(1))
    year = int(match.group(2))
    return f"{year}Q{quarter}", year, quarter, year * 4 + quarter


def parse_number(value) -> float:
    if value is None:
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan", "None"}:
        return np.nan
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace(",", "").replace("%", "").replace("\u00a0", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", "-", "."}:
        return np.nan
    try:
        number = float(text)
    except ValueError:
        return np.nan
    return -number if negative else number


def classify_segment(sector: str) -> str:
    if sector == "Banks":
        return "Banks"
    if sector == "Financial Services":
        return "Securities"
    if sector == "Insurance":
        return "Insurance"
    if sector == "Real Estate":
        return "Real Estate"
    if sector in FINANCIAL_SECTORS:
        return "Financials"
    return "Non-financial"


def extract_metadata(payload: dict) -> dict:
    ticker = payload.get("ticker")
    sector = "Unknown"
    sub_sector_id = None
    company_name = None
    market_cap = np.nan
    shares_outstanding = np.nan
    exchange = None
    matched_profile = {}

    raw_recent = (
        payload.get("loginStatus", {})
        .get("lsData", {})
        .get("recent-companies", "[]")
    )
    try:
        recent_companies = json.loads(raw_recent)
    except Exception:
        recent_companies = []

    for company in recent_companies:
        if company.get("symbol") == ticker:
            matched_profile = company
            break

    if matched_profile:
        sector = (matched_profile.get("sector") or {}).get("name") or sector
        sub_sector_id = matched_profile.get("sub_sector_id")
        company_name = matched_profile.get("name") or matched_profile.get("short_name")
        market_cap = parse_number(matched_profile.get("market_cap"))
        shares_outstanding = parse_number(matched_profile.get("shares_outstanding"))
        exchange = matched_profile.get("exchange_id")

    return {
        "ticker": ticker,
        "company_name": company_name or ticker,
        "sector": sector,
        "segment": classify_segment(sector),
        "sub_sector_id": sub_sector_id,
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "exchange": exchange,
        "source_url": payload.get("url"),
        "source_timestamp": payload.get("timestamp"),
    }


def iter_json_files(raw_dir: Path = RAW_JSON_DIR) -> Iterable[Path]:
    return sorted(raw_dir.glob("*_financial_report.json"))


def load_statement_rows(path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(path.read_text())
    metadata = extract_metadata(payload)
    rows: list[dict] = []

    for statement, table in (payload.get("financialData") or {}).items():
        table_rows = table.get("tableRows") or []
        if not table_rows:
            continue
        header = table_rows[0]
        periods = [parse_period(period) for period in header[1:]]

        for raw_row in table_rows[1:]:
            if not raw_row:
                continue
            label = clean_label(raw_row[0])
            if not label:
                continue
            item_key = normalize_key(label)
            for idx, raw_value in enumerate(raw_row[1:]):
                if idx >= len(periods):
                    break
                period, year, quarter, period_order = periods[idx]
                if period is None:
                    continue
                rows.append(
                    {
                        "ticker": metadata["ticker"],
                        "statement": statement,
                        "item_label": label,
                        "item_key": item_key,
                        "period": period,
                        "year": year,
                        "quarter": quarter,
                        "period_order": period_order,
                        "value": parse_number(raw_value),
                    }
                )
    return metadata, rows


def build_canonical_financials(
    statement_long: pd.DataFrame, metadata: pd.DataFrame
) -> pd.DataFrame:
    base_cols = ["ticker", "period", "year", "quarter", "period_order"]
    period_index = statement_long[base_cols].drop_duplicates()
    canonical = period_index.sort_values(["ticker", "period_order"]).reset_index(drop=True)

    for metric, candidates in CANONICAL_MAPPINGS.items():
        pieces = []
        for rank, (statement, label) in enumerate(candidates):
            key = normalize_key(label)
            match = statement_long[
                (statement_long["statement"] == statement)
                & (statement_long["item_key"] == key)
            ][base_cols + ["value"]].copy()
            if match.empty:
                continue
            match["source_rank"] = rank
            pieces.append(match)

        if not pieces:
            canonical[metric] = np.nan
            continue

        matches = pd.concat(pieces, ignore_index=True)
        matches = matches.sort_values(base_cols + ["source_rank"])
        matches = matches.drop_duplicates(["ticker", "period"], keep="first")
        canonical = canonical.merge(
            matches[["ticker", "period", "value"]],
            on=["ticker", "period"],
            how="left",
        ).rename(columns={"value": metric})

    canonical = canonical.merge(
        metadata[
            [
                "ticker",
                "company_name",
                "sector",
                "segment",
                "sub_sector_id",
                "market_cap",
                "shares_outstanding",
                "exchange",
            ]
        ],
        on="ticker",
        how="left",
    )
    canonical["total_debt"] = canonical[["short_term_debt", "long_term_debt"]].sum(
        axis=1, min_count=1
    )
    canonical["net_debt"] = canonical["total_debt"] - canonical["cash"]
    return canonical.sort_values(["ticker", "period_order"]).reset_index(drop=True)


def load_all(raw_dir: Path = RAW_JSON_DIR) -> LoadedData:
    metadata_rows: list[dict] = []
    statement_rows: list[dict] = []
    files = list(iter_json_files(raw_dir))
    if not files:
        raise FileNotFoundError(f"No financial JSON files found in {raw_dir}")

    for path in files:
        metadata, rows = load_statement_rows(path)
        metadata_rows.append(metadata)
        statement_rows.extend(rows)

    metadata_df = pd.DataFrame(metadata_rows).sort_values("ticker").reset_index(drop=True)
    statement_long = pd.DataFrame(statement_rows)
    statement_long = statement_long.merge(
        metadata_df[["ticker", "sector", "segment"]],
        on="ticker",
        how="left",
    )
    canonical = build_canonical_financials(statement_long, metadata_df)
    return LoadedData(metadata=metadata_df, statement_long=statement_long, canonical=canonical)
