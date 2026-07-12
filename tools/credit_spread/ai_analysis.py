"""Canonical AI-analysis contract for the Vietnam credit-spread tool."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from config import AI_PROVIDER_MAP, AI_TEMPERATURE, DATA_LAKE, ROOT_DIR
from tools.credit_spread.quant.metrics import calculate_credit_spread, load_issuance_data


CACHE_PREFIX = "credit_spread"
CACHE_VERSION = "primary_issuance_equal_weight_v1"
CACHE_VERSION_HEADER = "ai-cio-cache-version"
DEFAULT_ISSUANCE_PATH = DATA_LAKE / "credit_spread" / "vbma_corp_bond_issuance_detail.csv"
PROMPT_PATH = ROOT_DIR / "promt" / "credit_spread_promt.md"


def cache_path(provider_key: str, run_date: date | None = None) -> Path:
    date_key = (run_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{CACHE_PREFIX}_{provider_key}_{date_key}.txt"


def encode_cache(content: str) -> str:
    marker = f"<!-- {CACHE_VERSION_HEADER}: {CACHE_VERSION} -->\n"
    text = str(content or "")
    return text if text.startswith(marker) else marker + text


def decode_cache(content: str) -> str | None:
    marker = f"<!-- {CACHE_VERSION_HEADER}: {CACHE_VERSION} -->"
    text = str(content or "").lstrip()
    if not text.startswith(marker):
        return None
    return text[len(marker):].lstrip("\r\n")


def read_cached_analysis(path: Path, expected_data_date: str | None = None) -> str | None:
    if not path.exists():
        return None
    decoded = decode_cache(path.read_text(encoding="utf-8"))
    if decoded is None:
        return None
    if expected_data_date and not is_report_current(decoded, expected_data_date):
        return None
    return decoded


def write_cached_analysis(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_cache(content), encoding="utf-8")
    return path


def _coverage_by_sector(issuance: pd.DataFrame) -> dict[str, float]:
    target = issuance.loc[issuance["sector"].isin(["bank", "real_estate"])].copy()
    target["coupon_valid"] = target["coupon_rate_pct"].notna()
    coverage = target.groupby("sector", observed=True)["coupon_valid"].mean().mul(100.0)
    return {sector: float(coverage.get(sector, 0.0)) for sector in ("bank", "real_estate")}


def _trend_label(current_direction: str, change_3p_bps: float | None) -> str:
    if change_3p_bps is not None and change_3p_bps >= 25:
        return "WIDENING_3P"
    if change_3p_bps is not None and change_3p_bps <= -25:
        return "NARROWING_3P"
    if current_direction == "WIDENING":
        return "WIDENING_LATEST"
    if current_direction == "NARROWING":
        return "NARROWING_LATEST"
    return "STABLE_OR_MIXED"


def _data_quality(
    matched_periods: int,
    latest_bank_count: int,
    latest_real_estate_count: int,
    coverage: dict[str, float],
) -> str:
    minimum_latest_count = min(latest_bank_count, latest_real_estate_count)
    minimum_coverage = min(coverage.values())
    if matched_periods >= 16 and minimum_latest_count >= 5 and minimum_coverage >= 50:
        return "HIGH"
    if matched_periods >= 8 and minimum_latest_count >= 2 and minimum_coverage >= 35:
        return "MEDIUM"
    return "LOW"


def build_credit_spread_snapshot(
    issuance: pd.DataFrame,
    *,
    table_rows: int = 8,
) -> dict[str, Any]:
    """Build the canonical all-maturity, equal-weight snapshot used by UI and AI CIO."""
    spread = calculate_credit_spread(issuance, weighting="equal")
    if spread.empty:
        raise ValueError("Khong co ky matched hop le de tao Credit Spread AI snapshot")

    latest = spread.iloc[-1]
    risk_history = spread["risk_premium_bps"]
    latest_risk = float(latest["risk_premium_bps"])
    prior_risk = float(risk_history.iloc[-2]) if len(risk_history) >= 2 else None
    risk_change = latest_risk - prior_risk if prior_risk is not None else None
    change_3p = latest_risk - float(risk_history.iloc[-4]) if len(risk_history) >= 4 else None
    history_std = float(risk_history.std(ddof=1)) if len(risk_history) >= 2 else None
    history_mean = float(risk_history.mean())
    history_zscore = (
        (latest_risk - history_mean) / history_std
        if history_std is not None and history_std > 0
        else None
    )
    percentile = float(risk_history.rank(method="average", pct=True).iloc[-1] * 100.0)
    coverage = _coverage_by_sector(issuance)
    bank_count = int(latest["bank_issuance_count"])
    real_estate_count = int(latest["real_estate_issuance_count"])
    current_direction = str(latest["direction"])
    quality = _data_quality(len(spread), bank_count, real_estate_count, coverage)

    recent = spread.tail(max(1, table_rows)).reset_index()[
        [
            "report_date",
            "bank_yield_pct",
            "real_estate_yield_pct",
            "risk_premium_bps",
            "bank_issuance_count",
            "real_estate_issuance_count",
            "direction",
        ]
    ].copy()
    recent["report_date"] = recent["report_date"].dt.strftime("%d/%m/%Y")
    recent[["bank_yield_pct", "real_estate_yield_pct"]] = recent[
        ["bank_yield_pct", "real_estate_yield_pct"]
    ].round(2)
    recent["risk_premium_bps"] = recent["risk_premium_bps"].round(0)

    return {
        "date": spread.index[-1].strftime("%d/%m/%Y"),
        "data_date_iso": spread.index[-1].strftime("%Y-%m-%d"),
        "bank_yield_pct": float(latest["bank_yield_pct"]),
        "real_estate_yield_pct": float(latest["real_estate_yield_pct"]),
        "signed_spread_pct": float(latest["signed_spread_pct"]),
        "risk_premium_bps": latest_risk,
        "risk_premium_change_bps": risk_change,
        "risk_premium_change_3p_bps": change_3p,
        "risk_premium_history_mean_bps": history_mean,
        "risk_premium_history_zscore": history_zscore,
        "risk_premium_percentile": percentile,
        "direction": current_direction,
        "trend_3p": _trend_label(current_direction, change_3p),
        "matched_periods": int(len(spread)),
        "bank_issuance_count": bank_count,
        "real_estate_issuance_count": real_estate_count,
        "bank_coupon_coverage_pct": coverage["bank"],
        "real_estate_coupon_coverage_pct": coverage["real_estate"],
        "data_quality": quality,
        "weighting": "equal",
        "maturity_scope": "all",
        "recent_table": recent.to_markdown(index=False),
    }


def load_canonical_snapshot(path: str | Path = DEFAULT_ISSUANCE_PATH) -> dict[str, Any]:
    return build_credit_spread_snapshot(load_issuance_data(path))


def _fmt(value: Any, digits: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    sign = "+" if signed else ""
    return f"{float(value):{sign}.{digits}f}"


def build_credit_spread_prompt(snapshot: dict[str, Any]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    replacements = {
        "{date}": snapshot["date"],
        "{bank_yield_pct}": _fmt(snapshot["bank_yield_pct"], 2),
        "{real_estate_yield_pct}": _fmt(snapshot["real_estate_yield_pct"], 2),
        "{signed_spread_pct}": _fmt(snapshot["signed_spread_pct"], 2, signed=True),
        "{risk_premium_bps}": _fmt(snapshot["risk_premium_bps"], 1),
        "{risk_premium_change_bps}": _fmt(snapshot["risk_premium_change_bps"], 1, signed=True),
        "{risk_premium_change_3p_bps}": _fmt(snapshot["risk_premium_change_3p_bps"], 1, signed=True),
        "{risk_premium_percentile}": _fmt(snapshot["risk_premium_percentile"], 1),
        "{risk_premium_history_zscore}": _fmt(snapshot["risk_premium_history_zscore"], 2, signed=True),
        "{direction}": snapshot["direction"],
        "{trend_3p}": snapshot["trend_3p"],
        "{matched_periods}": str(snapshot["matched_periods"]),
        "{bank_issuance_count}": str(snapshot["bank_issuance_count"]),
        "{real_estate_issuance_count}": str(snapshot["real_estate_issuance_count"]),
        "{bank_coupon_coverage_pct}": _fmt(snapshot["bank_coupon_coverage_pct"], 1),
        "{real_estate_coupon_coverage_pct}": _fmt(snapshot["real_estate_coupon_coverage_pct"], 1),
        "{data_quality}": snapshot["data_quality"],
        "{recent_table}": snapshot["recent_table"],
    }
    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    unresolved = [placeholder for placeholder in replacements if placeholder in prompt]
    if unresolved:
        raise ValueError(f"Credit Spread prompt con placeholder: {unresolved}")
    return prompt


def build_structured_context(snapshot: dict[str, Any], ai_report: str | None = None) -> str:
    context = f"""=== CREDIT SPREAD CANONICAL SNAPSHOT ===
Credit Spread Data Date: {snapshot['date']}
Credit Spread Bank Yield: {snapshot['bank_yield_pct']:.2f}%
Credit Spread Real Estate Yield: {snapshot['real_estate_yield_pct']:.2f}%
Credit Spread Signed Bank Minus Real Estate: {snapshot['signed_spread_pct']:+.2f} percentage points
Credit Spread Risk Premium: {snapshot['risk_premium_bps']:.1f} bps
Credit Spread Risk Premium Change: {_fmt(snapshot['risk_premium_change_bps'], 1, signed=True)} bps
Credit Spread Risk Premium 3P Change: {_fmt(snapshot['risk_premium_change_3p_bps'], 1, signed=True)} bps
Credit Spread Risk Premium Percentile: {snapshot['risk_premium_percentile']:.1f}
Credit Spread Risk Premium History ZScore: {_fmt(snapshot['risk_premium_history_zscore'], 2, signed=True)}
Credit Spread Direction: {snapshot['direction']}
Credit Spread Trend 3P: {snapshot['trend_3p']}
Credit Spread Matched Periods: {snapshot['matched_periods']}
Credit Spread Bank Issuance Count: {snapshot['bank_issuance_count']}
Credit Spread Real Estate Issuance Count: {snapshot['real_estate_issuance_count']}
Credit Spread Bank Coupon Coverage: {snapshot['bank_coupon_coverage_pct']:.1f}%
Credit Spread Real Estate Coupon Coverage: {snapshot['real_estate_coupon_coverage_pct']:.1f}%
Credit Spread Data Quality: {snapshot['data_quality']}
Credit Spread Method: primary issuance, equal weight per fixed-coupon issue, all maturity buckets

Interpretation guardrails:
- Widening means the real-estate funding premium over banks increased; narrowing means it decreased.
- This is primary-issuance coupon evidence, not secondary-market OAS or a default-probability estimate.
- Do not infer issuer rating, collateral, covenant, SBV policy, or causality absent direct input.
""".strip()
    if ai_report:
        context += "\n\n=== CREDIT SPREAD AI INTERPRETATION - SUPPORTING PROSE ===\n" + ai_report.strip()
    return context


def append_structured_footer(report: str, snapshot: dict[str, Any]) -> str:
    """Attach deterministic metrics so downstream AI CIO never parses prose alone."""
    footer = "\n".join(
        [
            f"Credit Spread Data Date: {snapshot['date']}",
            f"Credit Spread Risk Premium: {snapshot['risk_premium_bps']:.1f} bps",
            f"Credit Spread Risk Premium Change: {_fmt(snapshot['risk_premium_change_bps'], 1, signed=True)} bps",
            f"Credit Spread Risk Premium 3P Change: {_fmt(snapshot['risk_premium_change_3p_bps'], 1, signed=True)} bps",
            f"Credit Spread Risk Premium Percentile: {snapshot['risk_premium_percentile']:.1f}",
            f"Credit Spread Matched Periods: {snapshot['matched_periods']}",
            f"Credit Spread Bank Issuance Count: {snapshot['bank_issuance_count']}",
            f"Credit Spread Real Estate Issuance Count: {snapshot['real_estate_issuance_count']}",
            f"Credit Spread Direction: {snapshot['direction']}",
            f"Credit Spread Data Quality: {snapshot['data_quality']}",
        ]
    )
    return str(report or "").rstrip() + "\n\n=== AI CIO STRUCTURED METRICS: credit_spread_canonical ===\n" + footer + "\n"


def is_report_current(report: str, expected_data_date: str) -> bool:
    return f"Credit Spread Data Date: {expected_data_date}" in str(report or "")


def run_ai_analysis(
    *,
    snapshot: dict[str, Any],
    provider_key: str,
    api_key: str | None = None,
    client=None,
    model: str | None = None,
) -> str:
    """Call the configured LLM using the canonical deterministic snapshot."""
    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["kimi-2.6"])
    if client is None:
        if not api_key:
            raise ValueError("API key rong")
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key.strip(),
            base_url=cfg["base_url"],
            timeout=cfg.get("timeout", 180),
        )

    full_prompt = build_credit_spread_prompt(snapshot)
    parts = full_prompt.split("# INPUT DATA", maxsplit=1)
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    response = client.chat.completions.create(
        model=model or cfg["api_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=cfg.get("temperature", AI_TEMPERATURE),
    )
    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("AI tra ve noi dung rong")
    return append_structured_footer(str(result), snapshot)
