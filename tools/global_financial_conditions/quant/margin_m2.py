"""
US margin debt / M2 overlay.

This module is intentionally separate from GFCM PCA logic. FINRA margin debt is
monthly and lagged, so it is used only as a structural speculative-leverage
overlay for dashboards and AI CIO context.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import re
from typing import Iterable
from urllib.parse import urljoin

import numpy as np
import pandas as pd

from config import DATA_LAKE

FINRA_MARGIN_PAGE_URL = (
    "https://www.finra.org/rules-guidance/key-topics/"
    "margin-accounts/margin-statistics"
)
FINRA_MARGIN_XLSX_URL = (
    "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
)
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_M2_SERIES_ID = "M2SL"
MARGIN_M2_CACHE = DATA_LAKE / "us_margin_debt_m2_cache.csv"
MARGIN_M2_START_DATE = "1997-01-01"

REQUIRED_COLUMNS = [
    "date",
    "margin_debt_million_usd",
    "m2_billion_usd",
    "margin_debt_pct_m2",
    "finra_source_url",
    "fred_series_id",
    "last_updated_at",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_col(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _month_end(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    return parsed.dt.to_period("M").dt.to_timestamp("M")


def _numeric(values: pd.Series) -> pd.Series:
    cleaned = (
        values.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("nan", "", regex=False)
    )
    cleaned = cleaned.replace({"": np.nan, ".": np.nan, "None": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def _rolling_percentile_100(
    series: pd.Series, window: int, min_periods: int
) -> pd.Series:
    def rank_last(values: Iterable[float]) -> float:
        ranked = pd.Series(values).rank(pct=True)
        return float(ranked.iloc[-1] * 100)

    return series.rolling(window=window, min_periods=min_periods).apply(rank_last, raw=False)


def discover_finra_excel_url(page_url: str = FINRA_MARGIN_PAGE_URL) -> str:
    """Discover FINRA margin-statistics Excel URL, with a stable fallback."""
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("Thiếu thư viện 'requests'. Cài đặt: pip install requests") from e

    headers = {"User-Agent": "Mozilla/5.0 onl-quant-platform/1.0"}
    response = requests.get(page_url, headers=headers, timeout=30)
    response.raise_for_status()

    hrefs = re.findall(r'href=["\']([^"\']+\.xlsx?)["\']', response.text, flags=re.I)
    candidates = [urljoin(page_url, href) for href in hrefs]
    if not candidates:
        return FINRA_MARGIN_XLSX_URL

    preferred = [url for url in candidates if "margin" in url.lower()]
    return preferred[0] if preferred else candidates[0]


def fetch_finra_margin_debt(source_url: str | None = None) -> pd.DataFrame:
    """
    Fetch FINRA debit balances in customers' securities margin accounts.

    Returns a monthly DataFrame with values in million USD. The parser searches
    the workbook for a header containing both "debit" and "margin" to avoid
    binding to one specific sheet layout.
    """
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("Thiếu thư viện 'requests'. Cài đặt: pip install requests") from e

    if source_url:
        url = source_url
    else:
        try:
            url = discover_finra_excel_url()
        except Exception:
            url = FINRA_MARGIN_XLSX_URL
    headers = {"User-Agent": "Mozilla/5.0 onl-quant-platform/1.0"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()

    try:
        workbook = pd.ExcelFile(BytesIO(response.content))
    except Exception as e:
        raise RuntimeError(f"Không đọc được FINRA Excel workbook: {e}") from e

    for sheet_name in workbook.sheet_names:
        raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
        parsed = _parse_finra_margin_sheet(raw, url)
        if not parsed.empty:
            return parsed

    raise RuntimeError("Không tìm thấy cột FINRA margin debt phù hợp trong workbook.")


def _parse_finra_margin_sheet(raw: pd.DataFrame, source_url: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    max_header_row = min(80, len(raw))
    for header_idx in range(max_header_row):
        header = [_normalize_col(value) for value in raw.iloc[header_idx].tolist()]
        date_col = _find_date_column(header)
        margin_col = _find_margin_debt_column(header)
        if date_col is None or margin_col is None:
            continue

        table = raw.iloc[header_idx + 1 :, [date_col, margin_col]].copy()
        table.columns = ["date", "margin_debt_million_usd"]
        table["date"] = _month_end(table["date"])
        table["margin_debt_million_usd"] = _numeric(table["margin_debt_million_usd"])
        table = table.dropna(subset=["date", "margin_debt_million_usd"])
        table = table[table["margin_debt_million_usd"] > 0]
        if table.empty:
            continue

        table = (
            table.sort_values("date", kind="mergesort")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        table["finra_source_url"] = source_url
        return table

    return pd.DataFrame()


def _find_date_column(header: list[str]) -> int | None:
    for idx, value in enumerate(header):
        if value in {"date", "month", "month year"}:
            return idx
        if "date" in value or "month" in value:
            return idx
    return None


def _find_margin_debt_column(header: list[str]) -> int | None:
    candidates = []
    for idx, value in enumerate(header):
        if not value:
            continue
        if "debit" in value and "margin" in value:
            candidates.append((0, idx))
        elif "debit balance" in value:
            candidates.append((1, idx))
    if not candidates:
        return None
    return sorted(candidates)[0][1]


def fetch_fred_m2(
    api_key: str,
    observation_start: str = MARGIN_M2_START_DATE,
    series_id: str = FRED_M2_SERIES_ID,
) -> pd.DataFrame:
    """Fetch monthly FRED M2 money stock in billion USD."""
    if not api_key:
        raise RuntimeError("FRED_API_KEY rỗng. Vui lòng cấu hình trong .env hoặc config.")
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("Thiếu thư viện 'requests'. Cài đặt: pip install requests") from e

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
    }
    response = requests.get(FRED_OBSERVATIONS_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    observations = payload.get("observations", [])
    if not observations:
        raise RuntimeError(f"FRED series {series_id} trả về 0 quan sát.")

    df = pd.DataFrame(observations)
    df["date"] = _month_end(df["date"])
    df["m2_billion_usd"] = _numeric(df["value"])
    df = df.dropna(subset=["date", "m2_billion_usd"])
    df = df[df["m2_billion_usd"] > 0]
    df = (
        df[["date", "m2_billion_usd"]]
        .sort_values("date", kind="mergesort")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    df["fred_series_id"] = series_id
    return df


def combine_margin_and_m2(
    finra_df: pd.DataFrame,
    m2_df: pd.DataFrame,
    updated_at: str | None = None,
) -> pd.DataFrame:
    """Inner-join FINRA margin debt and FRED M2 by monthly period, without filling."""
    if finra_df is None or finra_df.empty:
        raise ValueError("FINRA margin debt DataFrame rỗng.")
    if m2_df is None or m2_df.empty:
        raise ValueError("FRED M2 DataFrame rỗng.")

    finra = finra_df.copy()
    m2 = m2_df.copy()
    finra["date"] = _month_end(finra["date"])
    m2["date"] = _month_end(m2["date"])
    finra = finra.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")
    m2 = m2.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")

    merged = pd.merge(finra, m2, on="date", how="inner", validate="one_to_one")
    if merged.empty:
        raise ValueError("Không có tháng giao nhau giữa FINRA margin debt và FRED M2.")

    merged["margin_debt_million_usd"] = pd.to_numeric(
        merged["margin_debt_million_usd"], errors="coerce"
    )
    merged["m2_billion_usd"] = pd.to_numeric(merged["m2_billion_usd"], errors="coerce")
    merged = merged.dropna(subset=["margin_debt_million_usd", "m2_billion_usd"])
    merged = merged[(merged["margin_debt_million_usd"] > 0) & (merged["m2_billion_usd"] > 0)]
    if merged.empty:
        raise ValueError("Không có dòng hợp lệ sau khi lọc giá trị dương.")

    merged["margin_debt_pct_m2"] = (
        merged["margin_debt_million_usd"] / (merged["m2_billion_usd"] * 1000.0) * 100.0
    )
    merged["last_updated_at"] = updated_at or _utc_now_iso()

    for col in ("finra_source_url", "fred_series_id"):
        if col not in merged.columns:
            merged[col] = ""

    merged = merged.sort_values("date", kind="mergesort").reset_index(drop=True)
    return add_margin_m2_features(merged)


def add_margin_m2_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = _month_end(out["date"])
    out = out.sort_values("date", kind="mergesort").reset_index(drop=True)

    out["margin_debt_yoy_pct"] = out["margin_debt_million_usd"].pct_change(12) * 100.0
    out["m2_yoy_pct"] = out["m2_billion_usd"].pct_change(12) * 100.0

    ratio = out["margin_debt_pct_m2"]
    rolling_mean_5y = ratio.rolling(window=60, min_periods=36).mean()
    rolling_std_5y = ratio.rolling(window=60, min_periods=36).std().replace(0, np.nan)
    out["margin_debt_pct_m2_zscore_5y"] = (ratio - rolling_mean_5y) / rolling_std_5y
    out["margin_debt_pct_m2_percentile_10y"] = _rolling_percentile_100(
        ratio, window=120, min_periods=60
    )
    out["signal_regime"] = [
        _classify_margin_m2_regime(z, p)
        for z, p in zip(
            out["margin_debt_pct_m2_zscore_5y"],
            out["margin_debt_pct_m2_percentile_10y"],
        )
    ]
    return out


def _classify_margin_m2_regime(zscore: float, percentile: float) -> str:
    z_ok = pd.notna(zscore)
    p_ok = pd.notna(percentile)
    elevated_z = z_ok and zscore >= 1.5
    elevated_p = p_ok and percentile >= 85.0
    low_z = z_ok and zscore <= -1.0
    low_p = p_ok and percentile <= 25.0

    if elevated_z and elevated_p:
        return "ELEVATED_LEVERAGE"
    if elevated_z or elevated_p:
        return "WATCH_ELEVATED"
    if low_z and low_p:
        return "DELEVERAGED"
    if low_z or low_p:
        return "WATCH_DELEVERAGING"
    return "NEUTRAL"


def validate_margin_m2(
    df: pd.DataFrame,
    allow_stale: bool = False,
    max_staleness_months: int = 3,
) -> None:
    """Raise ValueError if the monthly overlay cache violates basic data contracts."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Margin/M2 cache thiếu cột bắt buộc: {missing}")

    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("Margin/M2 cache có date không parse được.")
    if dates.dt.to_period("M").duplicated().any():
        raise ValueError("Margin/M2 cache có tháng bị trùng.")

    for col in ("margin_debt_million_usd", "m2_billion_usd", "margin_debt_pct_m2"):
        values = pd.to_numeric(df[col], errors="coerce")
        if values.isna().any() or (values <= 0).any():
            raise ValueError(f"Margin/M2 cache có giá trị không dương hoặc NaN ở {col}.")

    ratio = pd.to_numeric(df["margin_debt_pct_m2"], errors="coerce")
    if ((ratio < 0) | (ratio > 15)).any():
        raise ValueError("Margin debt / M2 vượt dải kiểm soát 0-15%. Kiểm tra unit.")

    latest = dates.max()
    if not allow_stale:
        stale_cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=max_staleness_months)
        if latest < stale_cutoff:
            raise ValueError(
                f"FINRA margin debt latest month stale ({latest.date()}); "
                f"older than {max_staleness_months} months."
            )


def load_cached_margin_m2(path=MARGIN_M2_CACHE) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"Margin/M2 cache thiếu cột date: {path}")

    df["date"] = _month_end(df["date"])
    df = df.dropna(subset=["date"])
    numeric_cols = [
        "margin_debt_million_usd",
        "m2_billion_usd",
        "margin_debt_pct_m2",
        "margin_debt_yoy_pct",
        "m2_yoy_pct",
        "margin_debt_pct_m2_zscore_5y",
        "margin_debt_pct_m2_percentile_10y",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.sort_values("date", kind="mergesort")
        .drop_duplicates(subset=["date"], keep="last")
        .set_index("date")
        .sort_index()
    )
    return df


def summarize_latest_margin_m2(df: pd.DataFrame) -> dict:
    empty = {
        "date": "N/A",
        "margin_debt_million_usd": None,
        "m2_billion_usd": None,
        "margin_debt_pct_m2": None,
        "margin_debt_yoy_pct": None,
        "m2_yoy_pct": None,
        "margin_debt_pct_m2_zscore_5y": None,
        "margin_debt_pct_m2_percentile_10y": None,
        "signal_regime": "N/A",
        "finra_source_url": "",
        "fred_series_id": FRED_M2_SERIES_ID,
        "last_updated_at": "",
    }
    if df is None or df.empty:
        return empty

    work = df.copy()
    if "date" in work.columns:
        work["date"] = _month_end(work["date"])
        work = work.set_index("date")
    work = work.sort_index()
    latest = work.dropna(subset=["margin_debt_pct_m2"]).iloc[-1:]
    if latest.empty:
        return empty

    row = latest.iloc[-1]
    latest_date = pd.to_datetime(latest.index[-1], errors="coerce")

    def number(col: str):
        value = row.get(col)
        return float(value) if pd.notna(value) else None

    return {
        "date": "N/A" if pd.isna(latest_date) else latest_date.strftime("%Y-%m-%d"),
        "margin_debt_million_usd": number("margin_debt_million_usd"),
        "m2_billion_usd": number("m2_billion_usd"),
        "margin_debt_pct_m2": number("margin_debt_pct_m2"),
        "margin_debt_yoy_pct": number("margin_debt_yoy_pct"),
        "m2_yoy_pct": number("m2_yoy_pct"),
        "margin_debt_pct_m2_zscore_5y": number("margin_debt_pct_m2_zscore_5y"),
        "margin_debt_pct_m2_percentile_10y": number("margin_debt_pct_m2_percentile_10y"),
        "signal_regime": str(row.get("signal_regime", "N/A")),
        "finra_source_url": str(row.get("finra_source_url", "")),
        "fred_series_id": str(row.get("fred_series_id", FRED_M2_SERIES_ID)),
        "last_updated_at": str(row.get("last_updated_at", "")),
    }
