from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


CRITICAL_FIELDS = [
    "price",
    "shares_outstanding",
    "reported_equity",
    "adjusted_book_value_per_share",
    "sustainable_roe",
    "cost_of_equity",
    "fair_value_per_share_rim",
]

RISK_FIELDS = [
    "npl_ratio",
    "group2_ratio",
    "provision_coverage",
    "casa_ratio",
    "ldr",
    "car",
    "beta",
]


def _missing(value: Any) -> bool:
    return value is None or pd.isna(value)


def _warning_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len([item for item in value if str(item).strip()])

    text = str(value).strip()
    if not text or text == "[]":
        return 0
    return len([part for part in text.split(";") if part.strip()])


def calculate_data_quality_flag(record: Mapping[str, Any]) -> str:
    """
    Classify data quality for one valuation row.

    High means the core valuation fields and main risk fields are populated.
    Medium means the valuation can run but has warnings or missing risk data.
    Low means a critical valuation field is missing or confidence is poor.
    """
    confidence = record.get("confidence_score", 100.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    critical_missing = [
        field for field in CRITICAL_FIELDS
        if field not in record or _missing(record.get(field))
    ]
    risk_missing = [
        field for field in RISK_FIELDS
        if field not in record or _missing(record.get(field))
    ]
    warnings = _warning_count(record.get("warnings"))

    if critical_missing or confidence_value < 70.0 or warnings >= 5:
        return "Low"
    if risk_missing or warnings > 0 or confidence_value < 90.0:
        return "Medium"
    return "High"
