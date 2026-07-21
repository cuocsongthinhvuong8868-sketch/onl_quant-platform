"""Snapshot hook for AI CIO using PVGO valuation data.

This is intentionally data-only: no AI call and no Streamlit dependency.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_LAKE
from tools.pvgo.freshness import (
    DEFAULT_MARKET_DATA_PATH,
    DEFAULT_MAX_SESSION_LAG,
    evaluate_pvgo_freshness,
)

DEFAULT_COE_PCT = 14.0
PVGO_DATA_PATH = DATA_LAKE / "pvgo" / "vnindex_valuation_history.csv"


def calculate_pvgo(pe: float, coe_pct: float = DEFAULT_COE_PCT) -> float:
    coe_dec = coe_pct / 100.0
    if pd.isna(pe) or pe <= 0 or coe_dec <= 0:
        return float("nan")
    return (1.0 - 1.0 / (coe_dec * pe)) * 100.0


def classify_pvgo(pvgo_pct: float) -> str:
    if pd.isna(pvgo_pct):
        return "N/A"
    if pvgo_pct < 0:
        return "Below steady-state value"
    if pvgo_pct < 20:
        return "Low expectations"
    if pvgo_pct < 35:
        return "Normal / fair"
    if pvgo_pct < 50:
        return "Elevated"
    if pvgo_pct < 65:
        return "Very high"
    return "Extreme"


def load_pvgo_history(path: str | Path = PVGO_DATA_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("close", "pe", "pb"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df.loc[df["pe"] <= 0, "pe"] = np.nan
    df.loc[df["pb"] <= 0, "pb"] = np.nan
    df["pe"] = df["pe"].interpolate(method="linear").ffill().bfill()
    df["pb"] = df["pb"].interpolate(method="linear").ffill().bfill()
    return df


def snapshot(
    coe_pct: float = DEFAULT_COE_PCT,
    path: str | Path = PVGO_DATA_PATH,
    market_data_path: str | Path = DEFAULT_MARKET_DATA_PATH,
    max_session_lag: int = DEFAULT_MAX_SESSION_LAG,
) -> dict[str, Any]:
    df = load_pvgo_history(path)
    if df.empty:
        return {
            "status": "DATA INSUFFICIENT",
            "reason": f"PVGO valuation history not found or empty at {path}",
            "freshness": evaluate_pvgo_freshness(
                None,
                market_data_path=market_data_path,
                max_session_lag=max_session_lag,
            ),
        }

    latest = df.iloc[-1]
    pe = float(latest["pe"])
    pb = float(latest["pb"])
    close = float(latest["close"])
    pvgo_pct = calculate_pvgo(pe, coe_pct)
    steady_state_pe = 1.0 / (coe_pct / 100.0)
    status = classify_pvgo(pvgo_pct)
    hist_pvgo = df["pe"].apply(lambda value: calculate_pvgo(float(value), coe_pct))
    freshness = evaluate_pvgo_freshness(
        latest["date"],
        market_data_path=market_data_path,
        max_session_lag=max_session_lag,
    )

    return {
        "status": "OK",
        "date": latest["date"].strftime("%d/%m/%Y"),
        "close": close,
        "pe": pe,
        "pb": pb,
        "coe_pct": coe_pct,
        "steady_state_pe": steady_state_pe,
        "pvgo_pct": float(pvgo_pct),
        "pvgo_status": status,
        "pvgo_avg": float(hist_pvgo.mean()),
        "pvgo_zscore": float((pvgo_pct - hist_pvgo.mean()) / hist_pvgo.std()) if hist_pvgo.std() else 0.0,
        "rows": int(len(df)),
        "source": latest.get("source", "24hmoney:key-statistic-history"),
        "scraped_at": latest.get("scraped_at", ""),
        "freshness": freshness,
    }


def build_ai_cio_context(
    coe_pct: float = DEFAULT_COE_PCT,
    path: str | Path = PVGO_DATA_PATH,
    market_data_path: str | Path = DEFAULT_MARKET_DATA_PATH,
    max_session_lag: int = DEFAULT_MAX_SESSION_LAG,
) -> str:
    snap = snapshot(
        coe_pct=coe_pct,
        path=path,
        market_data_path=market_data_path,
        max_session_lag=max_session_lag,
    )
    if snap.get("status") != "OK":
        return f"DATA INSUFFICIENT - PVGO valuation feed unavailable: {snap.get('reason', 'unknown')}"

    freshness = snap["freshness"]
    if freshness["status"] == "STALE":
        return (
            "DATA INSUFFICIENT - PVGO valuation feed STALE: "
            f"source {freshness['source_date']} is {freshness['session_lag']} market sessions behind "
            f"{freshness['market_date']} (limit {freshness['max_session_lag']})."
        )

    return f"""
=== PVGO VALUATION STRUCTURED SNAPSHOT ===
- Date: {snap['date']}
- VN-Index close: {snap['close']:.2f}
- P/E: {snap['pe']:.2f}x
- P/B: {snap['pb']:.2f}x
- COE assumption: {snap['coe_pct']:.1f}%
- Steady-state P/E: {snap['steady_state_pe']:.2f}x
- PVGO: {snap['pvgo_pct']:.2f}%
- PVGO status: {snap['pvgo_status']}
- PVGO historical average: {snap['pvgo_avg']:.2f}%
- PVGO z-score: {snap['pvgo_zscore']:+.2f}
- Source: {snap['source']}
- Freshness: {freshness['status']}
- Freshness source date: {freshness['source_date'] or 'unknown'}
- Latest market session: {freshness['market_date'] or 'unknown'}
- Market-session lag: {freshness['session_lag'] if freshness['session_lag'] is not None else 'unknown'} (limit {freshness['max_session_lag']})

Interpretation rule:
- Negative/low PVGO means the market embeds low growth expectations, potentially supportive if earnings quality holds.
- Elevated/very high/extreme PVGO means valuation depends heavily on growth expectations; treat as expectation-risk overlay for AI CIO allocation and confidence.
- If freshness is UNKNOWN, keep that uncertainty explicit and reduce confidence in the valuation overlay.
""".strip()
