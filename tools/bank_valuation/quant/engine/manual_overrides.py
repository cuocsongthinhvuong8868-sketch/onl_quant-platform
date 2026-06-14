from __future__ import annotations

from pathlib import Path
import unicodedata

import pandas as pd


def _column_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace("_", " ").split())


def _find_column(columns: list[str], aliases: set[str]) -> str | None:
    normalized = {_column_key(col): col for col in columns}
    for alias in aliases:
        found = normalized.get(_column_key(alias))
        if found is not None:
            return found
    return None


def _parse_car(value: object) -> float:
    if pd.isna(value):
        return float("nan")

    text = str(value).strip()
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()

    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        parsed = float(text)
    except ValueError:
        return float("nan")

    if is_percent or parsed > 1.0:
        parsed = parsed / 100.0
    return parsed


def _parse_date(value: object) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT

    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        parsed = pd.to_datetime(text, errors="coerce", format=fmt)
        if pd.notna(parsed):
            return parsed
    return pd.to_datetime(text, errors="coerce")


def _date_to_period(value: object) -> str | None:
    parsed = _parse_date(value)
    if pd.isna(parsed):
        return None
    quarter = ((int(parsed.month) - 1) // 3) + 1
    return f"Q{quarter} {int(parsed.year)}"


def load_manual_car_overrides(path: str | Path) -> pd.DataFrame:
    override_path = Path(path)
    if not override_path.exists():
        return pd.DataFrame(columns=["ticker", "period", "car_override", "car_disclosure_date", "car_source"])

    if override_path.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(override_path)
    else:
        raw = pd.read_csv(override_path)

    if raw.empty:
        return pd.DataFrame(columns=["ticker", "period", "car_override", "car_disclosure_date", "car_source"])

    columns = list(raw.columns)
    ticker_col = _find_column(columns, {"ticker", "ma", "mã", "code"})
    period_col = _find_column(columns, {"period", "ky", "ky cong bo", "reporting period"})
    date_col = _find_column(columns, {"disclosure date", "as of date", "ky cong bo moi nhat", "kỳ công bố mới nhất"})
    car_col = _find_column(columns, {"car", "car hop nhat", "car hợp nhất", "capital adequacy ratio"})
    source_col = _find_column(columns, {"source", "source note", "source_note"})

    if ticker_col is None or car_col is None:
        return pd.DataFrame(columns=["ticker", "period", "car_override", "car_disclosure_date", "car_source"])

    overrides = pd.DataFrame()
    overrides["ticker"] = raw[ticker_col].astype(str).str.upper().str.strip()
    overrides["period"] = raw[period_col].astype(str).str.strip() if period_col else None
    if date_col:
        disclosure_dates = raw[date_col].map(_parse_date)
        overrides["car_disclosure_date"] = disclosure_dates.dt.strftime("%Y-%m-%d")
        derived_periods = raw[date_col].map(_date_to_period)
        overrides["period"] = overrides["period"].where(overrides["period"].notna(), derived_periods)
    else:
        overrides["car_disclosure_date"] = ""

    overrides["car_override"] = raw[car_col].map(_parse_car)
    if source_col:
        overrides["car_source"] = raw[source_col].fillna("").astype(str)
    else:
        overrides["car_source"] = "manual_car_override"

    overrides = overrides.dropna(subset=["ticker", "period", "car_override"])
    overrides = overrides[overrides["ticker"].str.len() > 0]
    return overrides[["ticker", "period", "car_override", "car_disclosure_date", "car_source"]]


def apply_manual_car_overrides(df: pd.DataFrame, path: str | Path) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    overrides = load_manual_car_overrides(path)
    if overrides.empty:
        return df.copy()

    result = df.copy()
    merged = result.merge(overrides, on=["ticker", "period"], how="left")
    if "car" not in merged.columns:
        merged["car"] = float("nan")
    merged["car"] = merged["car_override"].fillna(pd.to_numeric(merged["car"], errors="coerce"))

    if "car_source" not in merged.columns:
        merged["car_source"] = ""
    if "car_disclosure_date" not in merged.columns:
        merged["car_disclosure_date"] = ""

    merged["car_source"] = merged["car_source"].fillna("")
    merged["car_disclosure_date"] = merged["car_disclosure_date"].fillna("")
    return merged.drop(columns=["car_override"])
