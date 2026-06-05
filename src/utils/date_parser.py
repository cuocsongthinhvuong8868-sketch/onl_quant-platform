from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


_QUARTER_ENDS = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        if year < 1900 or year > 2200:
            return None
        return date(year, month, day)
    except ValueError:
        return None


def _two_digit_year(value: int, today: date | None = None) -> int:
    today = today or date.today()
    year = 2000 + value if value <= 69 else 1900 + value
    if year > today.year + 1:
        year -= 100
    return year


def _parse_compact_8(value: str) -> date | None:
    # Prefer YYYYMMDD when the first four digits look like a year.
    year_first = int(value[:4])
    if 1900 <= year_first <= 2200:
        parsed = _safe_date(year_first, int(value[4:6]), int(value[6:8]))
        if parsed:
            return parsed

    # Otherwise use DDMMYYYY, which matches local report/cache names.
    return _safe_date(int(value[4:8]), int(value[2:4]), int(value[:2]))


def _parse_compact_6(value: str) -> date | None:
    # Prefer DDMMYY for cache names such as 040626.
    day = int(value[:2])
    month = int(value[2:4])
    year = _two_digit_year(int(value[4:6]))
    parsed = _safe_date(year, month, day)
    if parsed:
        return parsed

    # Fallback to YYMMDD if DDMMYY is impossible.
    year = _two_digit_year(int(value[:2]))
    return _safe_date(year, int(value[2:4]), int(value[4:6]))


def parse_date_value(value: object) -> date | None:
    """Parse a single date-like value into a date.

    The parser intentionally accepts common formats used in this repo and
    avoids pandas so it can be reused in unit tests and light CLI paths.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y%m%d",
        "%d%m%Y",
        "%d%m%y",
        "%Y-%m",
        "%Y/%m",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    dates = extract_dates_from_text(text)
    return max(dates) if dates else None


def extract_dates_from_text(text: str | Path) -> list[date]:
    """Extract all valid dates from free text or a file path."""

    value = str(text)
    found: list[date] = []

    for match in re.finditer(r"(?<!\d)(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)", value):
        parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            found.append(parsed)

    for match in re.finditer(r"(?<!\d)(\d{1,2})[-_./](\d{1,2})[-_./](\d{2,4})(?!\d)", value):
        year_raw = int(match.group(3))
        year = _two_digit_year(year_raw) if year_raw < 100 else year_raw
        # For slash-separated market data, MM/DD/YYYY is common when day > 12.
        month_first = _safe_date(year, int(match.group(1)), int(match.group(2)))
        day_first = _safe_date(year, int(match.group(2)), int(match.group(1)))
        parsed = month_first or day_first
        if parsed:
            found.append(parsed)

    for match in re.finditer(r"(?<!\d)(\d{8})(?!\d)", value):
        parsed = _parse_compact_8(match.group(1))
        if parsed:
            found.append(parsed)

    for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", value):
        parsed = _parse_compact_6(match.group(1))
        if parsed:
            found.append(parsed)

    for match in re.finditer(r"(?<!\d)(\d{4})[-_\s]?Q([1-4])(?!\d)", value, flags=re.IGNORECASE):
        year = int(match.group(1))
        quarter = int(match.group(2))
        month, day = _QUARTER_ENDS[quarter]
        parsed = _safe_date(year, month, day)
        if parsed:
            found.append(parsed)

    return found


def latest_date(values: Iterable[object]) -> date | None:
    parsed = [parse_date_value(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return max(parsed) if parsed else None

