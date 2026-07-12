"""Core calculations for Vietnam bank versus real-estate credit spreads.

The signed spread follows the supplied methodology exactly:

    signed spread = bank issue yield - real-estate issue yield

It is normally negative. ``risk_premium_pct`` exposes the same distance with a
positive sign so widening and narrowing are easier to read on a dashboard.
This module deliberately has no Streamlit dependency.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd


WeightingMethod = Literal["equal", "issue_value"]

ISSUANCE_REQUIRED_COLUMNS = {
    "report_date",
    "sector",
    "coupon_rate_pct",
    "issue_value_bn_vnd",
    "maturity_bucket",
}
AGGREGATED_REQUIRED_COLUMNS = {
    "report_date",
    "sector",
    "maturity_bucket",
    "yield_avg_pct",
}
GOVERNMENT_REQUIRED_COLUMNS = {"date", "tenor", "yield_pct"}
TARGET_SECTORS = ("bank", "real_estate")
MATURITY_TO_GOVERNMENT_TENOR = {
    "<=3Y": "3Y",
    "3Y_5Y": "5Y",
    ">5Y": "10Y",
}

SPREAD_COLUMNS = [
    "bank_yield_pct",
    "real_estate_yield_pct",
    "signed_spread_pct",
    "risk_premium_pct",
    "signed_spread_bps",
    "risk_premium_bps",
    "risk_premium_percentile",
    "spread_change_bps",
    "spread_return_pct",
    "direction",
    "bank_issuance_count",
    "real_estate_issuance_count",
    "bank_issue_value_bn_vnd",
    "real_estate_issue_value_bn_vnd",
]


def _require_columns(df: pd.DataFrame, required: set[str], source: str) -> None:
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"{source} thieu cot bat buoc: {missing}")


def load_issuance_data(path: str | Path) -> pd.DataFrame:
    """Load and normalize the issue-level VBMA data."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay du lieu phat hanh: {path}")
    df = pd.read_csv(path)
    _require_columns(df, ISSUANCE_REQUIRED_COLUMNS, path.name)
    return normalize_issuance_data(df)


def normalize_issuance_data(df: pd.DataFrame) -> pd.DataFrame:
    """Return a defensively typed issue-level frame without mutating input."""
    _require_columns(df, ISSUANCE_REQUIRED_COLUMNS, "issuance dataframe")
    clean = df.copy()
    clean["report_date"] = pd.to_datetime(clean["report_date"], errors="coerce").dt.normalize()
    clean["coupon_rate_pct"] = pd.to_numeric(clean["coupon_rate_pct"], errors="coerce")
    clean["issue_value_bn_vnd"] = pd.to_numeric(clean["issue_value_bn_vnd"], errors="coerce")
    clean["sector"] = clean["sector"].astype("string").str.strip().str.lower()
    clean["maturity_bucket"] = clean["maturity_bucket"].astype("string").str.strip()
    clean = clean.loc[clean["report_date"].notna()].copy()
    if clean.empty:
        raise ValueError("Du lieu phat hanh khong co report_date hop le")
    return clean.sort_values("report_date", kind="mergesort").reset_index(drop=True)


def load_aggregated_yields(path: str | Path) -> pd.DataFrame:
    """Load VBMA's pre-aggregated sector/maturity yields."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay du lieu loi suat doanh nghiep: {path}")
    df = pd.read_csv(path)
    _require_columns(df, AGGREGATED_REQUIRED_COLUMNS, path.name)
    clean = df.copy()
    clean["report_date"] = pd.to_datetime(clean["report_date"], errors="coerce").dt.normalize()
    clean["yield_avg_pct"] = pd.to_numeric(clean["yield_avg_pct"], errors="coerce")
    clean["sector"] = clean["sector"].astype("string").str.strip().str.lower()
    clean["maturity_bucket"] = clean["maturity_bucket"].astype("string").str.strip()
    return clean.dropna(subset=["report_date", "yield_avg_pct"]).sort_values("report_date").reset_index(drop=True)


def load_government_yields(path: str | Path) -> pd.DataFrame:
    """Load Vietnam government-bond yields used as a risk-free benchmark."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay du lieu loi suat TPCP: {path}")
    df = pd.read_csv(path)
    _require_columns(df, GOVERNMENT_REQUIRED_COLUMNS, path.name)
    clean = df.copy()
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.normalize()
    clean["yield_pct"] = pd.to_numeric(clean["yield_pct"], errors="coerce")
    clean["tenor"] = clean["tenor"].astype("string").str.strip().str.upper()
    return clean.dropna(subset=["date", "yield_pct"]).sort_values("date").reset_index(drop=True)


def _aggregate_group(group: pd.DataFrame, weighting: WeightingMethod) -> pd.Series:
    coupons = group["coupon_rate_pct"]
    valid_coupon = coupons.notna()
    if weighting == "equal":
        yield_pct = coupons.loc[valid_coupon].mean()
    else:
        weights = group["issue_value_bn_vnd"]
        valid = valid_coupon & weights.notna() & weights.gt(0)
        yield_pct = np.average(coupons.loc[valid], weights=weights.loc[valid]) if valid.any() else np.nan

    valid_values = group.loc[valid_coupon, "issue_value_bn_vnd"].dropna()
    return pd.Series(
        {
            "yield_pct": yield_pct,
            "issuance_count": int(valid_coupon.sum()),
            "issue_value_bn_vnd": valid_values.sum(min_count=1),
        }
    )


def _last_value_percentile(values: pd.Series) -> float:
    """Average-rank percentile of the last value within an expanding window."""
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if array.size == 0:
        return np.nan
    latest = array[-1]
    less = int(np.count_nonzero(array < latest))
    equal = int(np.count_nonzero(array == latest))
    average_rank = less + (equal + 1.0) / 2.0
    return average_rank / array.size * 100.0


def calculate_credit_spread(
    issuance: pd.DataFrame,
    *,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    maturity_buckets: Iterable[str] | None = None,
    weighting: WeightingMethod = "equal",
) -> pd.DataFrame:
    """Calculate matched-date bank/real-estate issue yields and spreads.

    Only report dates containing a valid yield for both sectors survive. The
    return follows the supplied guide: ``diff(signed_spread) / abs(lag) * 100``.
    """
    if weighting not in ("equal", "issue_value"):
        raise ValueError("weighting phai la 'equal' hoac 'issue_value'")

    clean = normalize_issuance_data(issuance)
    selected = clean.loc[clean["sector"].isin(TARGET_SECTORS)].copy()
    if start_date is not None:
        selected = selected.loc[selected["report_date"].ge(pd.Timestamp(start_date).normalize())]
    if end_date is not None:
        selected = selected.loc[selected["report_date"].le(pd.Timestamp(end_date).normalize())]
    if maturity_buckets is not None:
        buckets = {str(item) for item in maturity_buckets}
        selected = selected.loc[selected["maturity_bucket"].isin(buckets)]

    if selected.empty:
        return pd.DataFrame(columns=SPREAD_COLUMNS, index=pd.DatetimeIndex([], name="report_date"))

    records = []
    for (report_date, sector), group in selected.groupby(
        ["report_date", "sector"], observed=True, sort=True
    ):
        metrics = _aggregate_group(group, weighting)
        records.append({"report_date": report_date, "sector": sector, **metrics.to_dict()})
    grouped = pd.DataFrame.from_records(records)

    result = pd.DataFrame(index=sorted(grouped["report_date"].unique()))
    result.index = pd.DatetimeIndex(result.index, name="report_date")
    for sector in TARGET_SECTORS:
        sector_rows = grouped.loc[grouped["sector"].eq(sector)].set_index("report_date")
        result[f"{sector}_yield_pct"] = sector_rows["yield_pct"]
        result[f"{sector}_issuance_count"] = sector_rows["issuance_count"]
        result[f"{sector}_issue_value_bn_vnd"] = sector_rows["issue_value_bn_vnd"]

    result = result.dropna(subset=["bank_yield_pct", "real_estate_yield_pct"]).copy()
    if result.empty:
        return pd.DataFrame(columns=SPREAD_COLUMNS, index=pd.DatetimeIndex([], name="report_date"))

    result["signed_spread_pct"] = result["bank_yield_pct"] - result["real_estate_yield_pct"]
    result["risk_premium_pct"] = -result["signed_spread_pct"]
    result["signed_spread_bps"] = result["signed_spread_pct"] * 100.0
    result["risk_premium_bps"] = result["risk_premium_pct"] * 100.0
    result["risk_premium_percentile"] = result["risk_premium_bps"].expanding(min_periods=1).apply(
        _last_value_percentile,
        raw=False,
    )
    result["spread_change_bps"] = result["signed_spread_pct"].diff() * 100.0

    lag = result["signed_spread_pct"].shift()
    result["spread_return_pct"] = result["signed_spread_pct"].diff().div(lag.abs()).mul(100.0)
    result.loc[lag.eq(0), "spread_return_pct"] = np.nan

    premium_change = result["risk_premium_pct"].diff()
    result["direction"] = np.select(
        [premium_change.gt(1e-12), premium_change.lt(-1e-12)],
        ["WIDENING", "NARROWING"],
        default="UNCHANGED",
    )
    result.loc[premium_change.isna(), "direction"] = "N/A"

    count_cols = ["bank_issuance_count", "real_estate_issuance_count"]
    result[count_cols] = result[count_cols].astype(int)
    return result[SPREAD_COLUMNS]


def calculate_benchmark_spreads(
    corporate_yields: pd.DataFrame,
    government_yields: pd.DataFrame,
    *,
    max_lag_days: int = 21,
) -> pd.DataFrame:
    """Compare sector yields with the nearest prior maturity proxy for TPCP.

    Bucket proxies are 3Y for ``<=3Y``, 5Y for ``3Y_5Y`` and 10Y for ``>5Y``.
    A backward as-of join prevents future government yields leaking into a
    corporate report date.
    """
    _require_columns(corporate_yields, AGGREGATED_REQUIRED_COLUMNS, "corporate yields")
    _require_columns(government_yields, GOVERNMENT_REQUIRED_COLUMNS, "government yields")

    corp = corporate_yields.copy()
    corp["report_date"] = pd.to_datetime(corp["report_date"], errors="coerce").dt.normalize()
    corp["yield_avg_pct"] = pd.to_numeric(corp["yield_avg_pct"], errors="coerce")
    corp["sector"] = corp["sector"].astype("string").str.strip().str.lower()
    corp["maturity_bucket"] = corp["maturity_bucket"].astype("string").str.strip()
    corp = corp.loc[
        corp["sector"].isin(TARGET_SECTORS)
        & corp["maturity_bucket"].isin(MATURITY_TO_GOVERNMENT_TENOR)
    ].dropna(subset=["report_date", "yield_avg_pct"])

    gov = government_yields.copy()
    gov["date"] = pd.to_datetime(gov["date"], errors="coerce").dt.normalize()
    gov["yield_pct"] = pd.to_numeric(gov["yield_pct"], errors="coerce")
    gov["tenor"] = gov["tenor"].astype("string").str.strip().str.upper()
    gov = gov.dropna(subset=["date", "yield_pct"])

    frames: list[pd.DataFrame] = []
    for bucket, tenor in MATURITY_TO_GOVERNMENT_TENOR.items():
        left = corp.loc[corp["maturity_bucket"].eq(bucket)].sort_values("report_date")
        right = (
            gov.loc[gov["tenor"].eq(tenor), ["date", "yield_pct"]]
            .sort_values("date")
            .rename(columns={"date": "government_date", "yield_pct": "government_yield_pct"})
        )
        if left.empty or right.empty:
            continue
        matched = pd.merge_asof(
            left,
            right,
            left_on="report_date",
            right_on="government_date",
            direction="backward",
            tolerance=pd.Timedelta(days=max_lag_days),
        )
        matched["government_tenor"] = tenor
        frames.append(matched)

    columns = [
        "report_date",
        "sector",
        "maturity_bucket",
        "government_tenor",
        "yield_avg_pct",
        "government_date",
        "government_yield_pct",
        "government_spread_bps",
    ]
    if not frames:
        return pd.DataFrame(columns=columns)

    result = pd.concat(frames, ignore_index=True)
    result["government_spread_bps"] = (
        result["yield_avg_pct"] - result["government_yield_pct"]
    ) * 100.0
    return result[columns].sort_values(["report_date", "maturity_bucket", "sector"]).reset_index(drop=True)
