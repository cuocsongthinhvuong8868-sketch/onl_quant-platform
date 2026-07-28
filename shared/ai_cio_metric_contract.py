"""Authoritative metric resolution for AI CIO evidence packets.

The final AI CIO report must not infer live numbers from narrative prose when a
machine-readable value is available.  This module centralises that rule for all
tools and keeps the precedence explicit:

1. direct quantitative metrics emitted by code;
2. a tool-matched Structured Tail JSON object;
3. tool-specific prose regexes as a legacy fallback only.

Lower-priority candidates are retained for a consistency check but can never
override a higher-priority value.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DIRECT_METRIC_SOURCE = "direct_quantitative"
STRUCTURED_TAIL_SOURCE = "structured_tail_json"
PROSE_FALLBACK_SOURCE = "prose_regex_fallback"
SOURCE_PRIORITY = (
    DIRECT_METRIC_SOURCE,
    STRUCTURED_TAIL_SOURCE,
    PROSE_FALLBACK_SOURCE,
)


# Structured tails historically used short display keys while the scoring
# contract uses canonical names.  Unknown keys are preserved so every tool can
# expose additional machine-readable diagnostics without changing this module.
TOOL_METRIC_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fear_greed": {
        "fear_greed_score": ("fear_greed_score", "risk_score", "score"),
        "signal_confidence": ("signal_confidence",),
        "acute_shock": ("acute_shock",),
    },
    "manipulation": {
        "manip_slope": ("manip_slope", "slope"),
        "manip_corr": ("manip_corr", "correlation", "corr"),
        "manip_slope_percentile": (
            "manip_slope_percentile",
            "slope_percentile",
            "manip_pr_slope",
        ),
        "manip_corr_percentile": (
            "manip_corr_percentile",
            "corr_percentile",
            "manip_pr_corr",
        ),
    },
    "dispersion": {
        "dispersion_spread_z": ("dispersion_spread_z", "spread_z"),
        "dispersion_dpi_pct": ("dispersion_dpi_pct", "dpi_pct", "dpi"),
        "dispersion_avg_corr": (
            "dispersion_avg_corr",
            "avg_corr",
            "ledoit_corr",
        ),
        "dispersion_broad_stress_score": (
            "dispersion_broad_stress_score",
            "broad_stress_score",
        ),
        "downside_participation_pct": ("downside_participation_pct",),
    },
    "upside_ratio": {
        "p95_downside_pct": ("p95_downside_pct",),
        "p95_upside_pct": ("p95_upside_pct",),
        "phi_up": ("phi_up",),
        "phi_down": ("phi_down",),
        "breadth_stress_score": ("breadth_stress_score",),
        "net_sell_pressure_pct": ("net_sell_pressure_pct", "net_pressure"),
    },
    "bank_valuation": {
        "bank_valuation_breadth_score": (
            "bank_valuation_breadth_score",
            "breadth_score",
        ),
        "median_valuation_gap_pct": (
            "median_valuation_gap_pct",
            "median_valuation_gap",
        ),
        "eligible_banks": ("eligible_banks", "bank_count"),
    },
    "market_breadth": {
        "breadth_ma20_pct": ("breadth_ma20_pct", "ma20_pct"),
        "breadth_ma60_pct": ("breadth_ma60_pct", "ma60_pct"),
        "breadth_ma125_pct": ("breadth_ma125_pct", "ma125_pct"),
        "breadth_ma252_pct": ("breadth_ma252_pct", "ma252_pct"),
        "breadth_universe_size": ("breadth_universe_size", "universe_size"),
    },
    "esr_monitor": {
        "ssi_pct": ("ssi_pct",),
        "pca_concentration_pct": ("pca_concentration_pct",),
    },
    "va_res": {
        "vares_stress_index_pct": (
            "vares_stress_index_pct",
            "stress_index_pct",
            "stress_index",
        ),
        "vares_complacency_pct": (
            "vares_complacency_pct",
            "complacency_pct",
            "complacency_index",
        ),
        "vares_breach_count": ("vares_breach_count", "breach_count", "breached_count"),
        "vares_mispriced_count": (
            "vares_mispriced_count",
            "mispriced_count",
        ),
    },
    "var_cvar_vnindex": {
        "evt_xi": ("evt_xi", "xi"),
        "evt_xi_p05": ("evt_xi_p05", "xi_p05"),
        "evt_xi_p50": ("evt_xi_p50", "xi_p50"),
        "evt_xi_p95": ("evt_xi_p95", "xi_p95"),
        "evt_xi_min": ("evt_xi_min", "xi_min"),
        "evt_xi_max": ("evt_xi_max", "xi_max"),
        "evt_xi_range": ("evt_xi_range", "xi_range"),
        "evt_threshold_stable": ("evt_threshold_stable", "threshold_stable"),
        "evt_var_99_pct": ("evt_var_99_pct",),
        "evt_es_99_pct": ("evt_es_99_pct",),
        "evt_var99_range_pp": ("evt_var99_range_pp",),
        "evt_es99_range_pp": ("evt_es99_range_pp",),
    },
    "sentiment_factor_news": {
        "news_macro_composite": ("news_macro_composite", "macro_composite"),
        "news_confidence": ("news_confidence", "macro_composite_prob_pos"),
        "news_count": ("news_count",),
    },
    "risk_adjusted_growth": {
        "top_economic_alpha_pct": ("top_economic_alpha_pct", "top_alpha_pct"),
        "median_economic_alpha_pct": ("median_economic_alpha_pct", "median_alpha_pct"),
        "positive_alpha_count": ("positive_alpha_count",),
        "bank_count": ("bank_count", "ticker_count"),
    },
    "fed_liquidity": {
        "fed_net_liquidity": ("fed_net_liquidity", "net_liquidity"),
        "fed_liquidity_impulse": ("fed_liquidity_impulse", "impulse"),
        "fed_liquidity_impulse_ema": ("fed_liquidity_impulse_ema", "impulse_ema"),
        "fed_liquidity_zscore": ("fed_liquidity_zscore", "z_score"),
    },
    "global_financial_conditions": {
        "cqs_percentile": ("cqs_percentile", "cqs_pct"),
        "gfcm_pc1_percentile": ("gfcm_pc1_percentile", "pc1_pct"),
        "gfcm_pc1": ("gfcm_pc1", "pc1"),
        "gfcm_ccc_oas": ("gfcm_ccc_oas", "ccc_oas"),
    },
    "credit_spread": {
        "credit_spread_risk_premium_bps": (
            "credit_spread_risk_premium_bps",
            "risk_premium_bps",
        ),
        "credit_spread_change_bps": (
            "credit_spread_change_bps",
            "risk_premium_change_bps",
        ),
        "credit_spread_3p_change_bps": (
            "credit_spread_3p_change_bps",
            "risk_premium_change_3p_bps",
        ),
        "credit_spread_percentile": (
            "credit_spread_percentile",
            "risk_premium_percentile",
        ),
        "credit_spread_matched_periods": (
            "credit_spread_matched_periods",
            "matched_periods",
        ),
        "credit_spread_bank_count": (
            "credit_spread_bank_count",
            "bank_issuance_count",
        ),
        "credit_spread_real_estate_count": (
            "credit_spread_real_estate_count",
            "real_estate_issuance_count",
        ),
    },
    "margin_m2_overlay": {
        "margin_debt_pct_m2": ("margin_debt_pct_m2",),
        "margin_debt_yoy_pct": ("margin_debt_yoy_pct",),
        "m2_yoy_pct": ("m2_yoy_pct",),
        "margin_debt_pct_m2_zscore_5y": ("margin_debt_pct_m2_zscore_5y",),
        "margin_debt_pct_m2_percentile_10y": (
            "margin_debt_pct_m2_percentile_10y",
        ),
    },
    "vnibor": {
        "vnibor_on": ("vnibor_on", "overnight"),
        "vnibor_zscore": ("vnibor_zscore", "z_score"),
        "vnibor_percentile": ("vnibor_percentile", "percentile"),
        "vnibor_stress_warning_days_20d": ("vnibor_stress_warning_days_20d",),
    },
    "ltmm": {
        "ltmm_fli": ("ltmm_fli", "fli"),
        "ltmm_mli": ("ltmm_mli", "mli"),
        "ltmm_te": ("ltmm_te", "te"),
        "ltmm_fri_collateral": ("ltmm_fri_collateral", "fri_collateral"),
        "ltmm_fire_trigger_count": ("ltmm_fire_trigger_count", "fire_trigger_count"),
        "ltmm_transmission_breakdown_fire": (
            "ltmm_transmission_breakdown_fire",
            "transmission_breakdown_fire",
        ),
    },
    "vn100_corporate_health": {
        "vn100_health_score": ("vn100_health_score",),
        "revenue_breadth": ("revenue_breadth",),
        "profit_breadth": ("profit_breadth",),
        "cfo_breadth": ("cfo_breadth",),
        "healthy_growth_breadth": ("healthy_growth_breadth",),
        "working_capital_stress_index": ("working_capital_stress_index",),
        "leverage_stress_index": ("leverage_stress_index",),
    },
    "abm_simulator": {
        "abm_early_warning_score": ("abm_early_warning_score", "early_warning_score"),
        "distance_to_cascade_pct": ("distance_to_cascade_pct",),
        "panic_ratio_pct": ("panic_ratio_pct",),
        "abm_avg_leverage_ratio": ("abm_avg_leverage_ratio", "avg_leverage_ratio"),
        "cascade_vulnerability": ("cascade_vulnerability",),
        "abm_stress_confidence_pct": (
            "abm_stress_confidence_pct",
            "stress_confidence_pct",
        ),
    },
    "pvgo": {
        "pvgo_pct": ("pvgo_pct",),
        "pe": ("pe",),
        "coe_pct": ("coe_pct",),
    },
}


# Regex parsing is deliberately tool-specific.  A Market Breadth threshold in
# another report must never become the live Market Breadth metric.
PROSE_METRIC_PATTERNS_BY_TOOL: dict[str, dict[str, tuple[str, ...]]] = {
    "fear_greed": {
        "fear_greed_score": (
            r"FearGreed\s+Risk\s+Score\s*:\s*([-+]?\d+(?:\.\d+)?)",
            r"\bRisk\s+Score\s*:\s*([-+]?\d+(?:\.\d+)?)",
        ),
    },
    "manipulation": {
        "manip_slope": (r"\bslope\s*[=:]\s*([-+]?\d+(?:\.\d+)?)",),
        "manip_corr": (r"\bcorr(?:elation)?\s*[=:]\s*([-+]?\d+(?:\.\d+)?)",),
        "manip_slope_percentile": (
            r"slope\s+percentile\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "manip_corr_percentile": (
            r"corr(?:elation)?\s+percentile\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
        ),
    },
    "dispersion": {
        "dispersion_spread_z": (r"\bSpread[_ ]Z\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",),
        "dispersion_dpi_pct": (r"\bDPI\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",),
        "dispersion_avg_corr": (
            r"(?:Average|Avg|Ledoit)[_ ]Correlation\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "dispersion_broad_stress_score": (
            r"Broad\s+Stress\s+Score\s*:\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "downside_participation_pct": (
            r"Downside\s+Participation\s*:\s*([-+]?\d+(?:\.\d+)?)\s*%",
        ),
    },
    "upside_ratio": {
        "p95_downside_pct": (r"p95[_ ]downside(?:[_ ]pct)?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",),
        "p95_upside_pct": (r"p95[_ ]upside(?:[_ ]pct)?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",),
        "breadth_stress_score": (
            r"Breadth\s+Stress\s+Score\s*:\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "net_sell_pressure_pct": (
            r"Net\s+Sell\s+Pressure\s*:\s*([-+]?\d+(?:\.\d+)?)\s*pp",
        ),
    },
    "market_breadth": {
        "breadth_ma20_pct": (
            r"\bMA20\s*(?:\([^)]*\))?\s*[:=]\s*\**\s*([-+]?\d+(?:\.\d+)?)\s*%",
            r"(?:Tỷ\s+lệ\s+mã\s+trên|Số\s+mã\s*>)\s*MA20[^\n%]*?([-+]?\d+(?:\.\d+)?)\s*%",
            r'"ma20_pct"\s*:\s*([-+]?\d+(?:\.\d+)?)',
        ),
        "breadth_ma60_pct": (
            r"\bMA60\s*(?:\([^)]*\))?\s*[:=]\s*\**\s*([-+]?\d+(?:\.\d+)?)\s*%",
            r'"ma60_pct"\s*:\s*([-+]?\d+(?:\.\d+)?)',
        ),
        "breadth_ma125_pct": (
            r"\bMA125\s*(?:\([^)]*\))?\s*[:=]\s*\**\s*([-+]?\d+(?:\.\d+)?)\s*%",
            r'"ma125_pct"\s*:\s*([-+]?\d+(?:\.\d+)?)',
        ),
        "breadth_ma252_pct": (
            r"\bMA252\s*(?:\([^)]*\))?\s*[:=]\s*\**\s*([-+]?\d+(?:\.\d+)?)\s*%",
            r'"ma252_pct"\s*:\s*([-+]?\d+(?:\.\d+)?)',
        ),
    },
    "esr_monitor": {
        "ssi_pct": (r"\bSSI\b[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",),
    },
    "var_cvar_vnindex": {
        "evt_xi": (
            r"EVT\s+Xi(?:\s+MLE)?\s*:[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bxi_mle\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"Tail Index.*?([-+]?\d+(?:\.\d+)?)",
        ),
        "evt_xi_p05": (r"EVT\s+Xi\s+P05[^0-9-]*([-+]?\d+(?:\.\d+)?)",),
        "evt_xi_p50": (r"EVT\s+Xi\s+P50[^0-9-]*([-+]?\d+(?:\.\d+)?)",),
        "evt_xi_p95": (r"EVT\s+Xi\s+P95[^0-9-]*([-+]?\d+(?:\.\d+)?)",),
        "evt_xi_min": (
            r"EVT\s+Xi\s+Min[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bxi_min\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        ),
        "evt_xi_max": (
            r"EVT\s+Xi\s+Max[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bxi_max\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        ),
        "evt_xi_range": (
            r"EVT\s+Xi\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bxi_range\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        ),
        "evt_var99_range_pp": (
            r"EVT\s+VaR99\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*pp",
        ),
        "evt_es99_range_pp": (
            r"EVT\s+ES99\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*pp",
        ),
        "evt_threshold_stable": (r"EVT\s+Threshold\s+Stable[^0-9]*(0|1)",),
    },
    "global_financial_conditions": {
        "cqs_percentile": (
            r"\bCQS\s+Percentile(?:\s+\d+\s*[Yy])?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
            r"\bCQS\b[^\n]*?percentile(?:\s+\d+\s*[Yy])?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
            r"\bCQS\b\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
        ),
    },
    "vnibor": {
        "vnibor_on": (r"(?:Overnight|VNIBOR\s+ON)[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",),
    },
    "pvgo": {
        "pvgo_pct": (r"\bPVGO\b\s*:\s*([-+]?\d+(?:\.\d+)?)\s*%",),
        "pe": (r"\bP/E\b\s*:\s*([-+]?\d+(?:\.\d+)?)x",),
        "coe_pct": (r"\bCOE assumption\b\s*:\s*([-+]?\d+(?:\.\d+)?)\s*%",),
    },
    "abm_simulator": {
        "distance_to_cascade_pct": (
            r"Distance to Cascade[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",
        ),
        "panic_ratio_pct": (
            r"(?:Simulated\s+)?Panic Ratio[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",
        ),
        "abm_early_warning_score": (
            r"Early-warning Score[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*(?:/100)?",
        ),
        "abm_avg_leverage_ratio": (
            r"Avg Leverage Ratio[^0-9-]*([-+]?\d+(?:\.\d+)?)x?",
        ),
        "cascade_vulnerability": (
            r"Cascade Vulnerability[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        ),
        "abm_stress_confidence_pct": (
            r"Stress Confidence[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",
        ),
    },
    "ltmm": {
        "ltmm_fli": (r"LTMM\s+FLI\s*:\s*([-+]?\d+(?:\.\d+)?)",),
        "ltmm_mli": (r"LTMM\s+MLI\s*:\s*([-+]?\d+(?:\.\d+)?)",),
        "ltmm_te": (r"LTMM\s+TE\s*:\s*([-+]?\d+(?:\.\d+)?)",),
        "ltmm_fri_collateral": (
            r"LTMM\s+FRI_collateral\s*:\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "ltmm_fire_trigger_count": (r"LTMM\s+Fire\s+Trigger\s+Count\s*:\s*(\d+)",),
        "ltmm_transmission_breakdown_fire": (
            r"(?:LTMM\s+)?transmission_breakdown\s+FIRE\s*:\s*(\d+)",
        ),
    },
    "credit_spread": {
        "credit_spread_risk_premium_bps": (
            r"Credit\s+Spread\s+Risk\s+Premium\s*:\s*([-+]?\d+(?:\.\d+)?)\s*bps",
        ),
        "credit_spread_change_bps": (
            r"Credit\s+Spread\s+Risk\s+Premium\s+Change\s*:\s*([-+]?\d+(?:\.\d+)?)\s*bps",
        ),
        "credit_spread_3p_change_bps": (
            r"Credit\s+Spread\s+Risk\s+Premium\s+3P\s+Change\s*:\s*([-+]?\d+(?:\.\d+)?)\s*bps",
        ),
        "credit_spread_percentile": (
            r"Credit\s+Spread\s+Risk\s+Premium\s+Percentile\s*:\s*([-+]?\d+(?:\.\d+)?)",
        ),
        "credit_spread_matched_periods": (
            r"Credit\s+Spread\s+Matched\s+Periods\s*:\s*(\d+)",
        ),
        "credit_spread_bank_count": (
            r"Credit\s+Spread\s+Bank\s+Issuance\s+Count\s*:\s*(\d+)",
        ),
        "credit_spread_real_estate_count": (
            r"Credit\s+Spread\s+Real\s+Estate\s+Issuance\s+Count\s*:\s*(\d+)",
        ),
    },
}


# Compatibility for synthetic/legacy aggregate packets that are not registered
# tool IDs.  Production tools always use the tool-specific table above, so this
# cannot reintroduce cross-tool contamination into live AI CIO packets.
LEGACY_GENERIC_PROSE_PATTERNS: dict[str, tuple[str, ...]] = {
    "ssi_pct": (r"\bSSI\b[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%",),
    "evt_xi": (
        r"EVT\s+Xi(?:\s+MLE)?\s*:[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        r"Tail Index.*?([-+]?\d+(?:\.\d+)?)",
    ),
    "breadth_ma20_pct": (
        r"Breadth\s+MA20\s*[:=]\s*([-+]?\d+(?:\.\d+)?)\s*%",
    ),
    "cqs_percentile": (
        r"\bCQS\b\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
    ),
}


CONTROL_KEYS = frozenset({"tool", "date", "source", "metrics"})


@dataclass(frozen=True)
class MetricResolution:
    metrics: dict[str, Any]
    provenance: dict[str, str]
    consistency: dict[str, Any]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return number if math.isfinite(number) else None


def append_direct_metrics(report_text: str, tool_id: str, metrics: Mapping[str, Any]) -> str:
    """Append a code-generated, machine-readable metric contract to a child report."""

    payload = {
        "tool": str(tool_id),
        "source": DIRECT_METRIC_SOURCE,
        "metrics": _json_safe(dict(metrics)),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    return (
        str(report_text or "").rstrip()
        + f"\n\n=== AI CIO DIRECT METRICS: {tool_id} ===\n"
        + f"```json\n{body}\n```\n"
    )


def _tool_matches(expected: str, actual: Any) -> bool:
    def norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    return norm(expected) == norm(actual)


def _iter_json_objects(text: str) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    decoder = json.JSONDecoder()

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        candidate = match.group(1).strip()
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            marker = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
            if marker not in seen:
                seen.add(marker)
                yield payload

    # Some providers omit Markdown fences.  raw_decode lets us recover a valid
    # object without accepting arbitrary surrounding prose.
    for match in re.finditer(r"\{", text):
        try:
            payload, _ = decoder.raw_decode(text[match.start():])
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        marker = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        yield payload


def _alias_lookup(tool_id: str) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in TOOL_METRIC_ALIASES.get(tool_id, {}).items():
        lookup[canonical.lower()] = canonical
        for alias in aliases:
            lookup[str(alias).lower()] = canonical
    return lookup


def _canonicalize_metrics(tool_id: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    aliases = _alias_lookup(tool_id)
    output: dict[str, Any] = {}
    for raw_key, raw_value in metrics.items():
        key = str(raw_key).strip()
        if not key or key.lower() in CONTROL_KEYS or raw_value is None:
            continue
        canonical = aliases.get(key.lower(), key)
        value = _json_safe(raw_value)
        if value is not None:
            output[canonical] = value
    return output


def _extract_structured_candidates(
    tool_id: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    direct: dict[str, Any] = {}
    structured: dict[str, Any] = {}
    for payload in _iter_json_objects(text):
        if not _tool_matches(tool_id, payload.get("tool")):
            continue
        source = str(payload.get("source") or "").strip().lower()
        if source == DIRECT_METRIC_SOURCE and isinstance(payload.get("metrics"), Mapping):
            direct.update(_canonicalize_metrics(tool_id, payload["metrics"]))
            continue
        structured.update(_canonicalize_metrics(tool_id, payload))
    return direct, structured


def _extract_first_number(patterns: Iterable[str], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except Exception:
            continue
        if math.isfinite(value):
            return value
    return None


def _extract_prose_candidates(tool_id: str, text: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    patterns_by_metric = PROSE_METRIC_PATTERNS_BY_TOOL.get(tool_id)
    if patterns_by_metric is None and tool_id not in TOOL_METRIC_ALIASES:
        patterns_by_metric = LEGACY_GENERIC_PROSE_PATTERNS
    for metric, patterns in (patterns_by_metric or {}).items():
        value = _extract_first_number(patterns, text)
        if value is not None:
            output[metric] = value
    return output


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_tolerance(metric: str, left: float, right: float) -> float:
    key = metric.lower()
    if key.startswith("evt_xi"):
        return 0.005
    if key.endswith("_count") or key.endswith("_periods") or key.endswith("_size"):
        return 0.0
    if key.endswith("_pct") or key.endswith("_percentile") or key.endswith("_pp"):
        return 0.20
    if key.endswith("_bps"):
        return 1.0
    return max(1e-6, 0.01 * max(abs(left), abs(right), 1.0))


def _numeric_mismatch(metric: str, authoritative: Any, candidate: Any) -> tuple[bool, float | None]:
    left = _as_number(authoritative)
    right = _as_number(candidate)
    if left is None or right is None:
        return False, None
    delta = abs(left - right)
    return delta > _metric_tolerance(metric, left, right), delta


def resolve_tool_metrics(
    tool_id: str,
    report_text: str,
    *,
    direct_metrics: Mapping[str, Any] | None = None,
) -> MetricResolution:
    """Resolve metrics with strict source precedence and mismatch blocking."""

    text = str(report_text or "")
    embedded_direct, structured = _extract_structured_candidates(tool_id, text)
    direct = dict(embedded_direct)
    if direct_metrics:
        # An in-memory computation is newer and more authoritative than a cache
        # footer, though both are classified as direct quantitative evidence.
        direct.update(_canonicalize_metrics(tool_id, direct_metrics))
    prose = _extract_prose_candidates(tool_id, text)
    candidates = {
        DIRECT_METRIC_SOURCE: direct,
        STRUCTURED_TAIL_SOURCE: structured,
        PROSE_FALLBACK_SOURCE: prose,
    }

    resolved: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for source in SOURCE_PRIORITY:
        for metric, value in candidates[source].items():
            if metric not in resolved:
                resolved[metric] = value
                provenance[metric] = source

    warnings: list[str] = []
    blocked: list[dict[str, Any]] = []
    for metric, authoritative_value in resolved.items():
        authoritative_source = provenance[metric]
        authoritative_rank = SOURCE_PRIORITY.index(authoritative_source)
        for source in SOURCE_PRIORITY[authoritative_rank + 1:]:
            if metric not in candidates[source]:
                continue
            candidate_value = candidates[source][metric]
            mismatch, delta = _numeric_mismatch(metric, authoritative_value, candidate_value)
            if not mismatch:
                continue
            detail = {
                "metric": metric,
                "authoritative_source": authoritative_source,
                "authoritative_value": authoritative_value,
                "blocked_source": source,
                "blocked_value": candidate_value,
                "absolute_delta": delta,
            }
            blocked.append(detail)
            warnings.append(
                f"{metric}: kept {authoritative_source}={authoritative_value}; "
                f"blocked {source}={candidate_value}"
            )

    sources_used = sorted(set(provenance.values()), key=SOURCE_PRIORITY.index)
    if blocked:
        status = "WARN_BLOCKED_LOWER_PRIORITY"
    elif DIRECT_METRIC_SOURCE in sources_used:
        status = "PASS_DIRECT"
    elif STRUCTURED_TAIL_SOURCE in sources_used:
        status = "PASS_STRUCTURED"
    elif PROSE_FALLBACK_SOURCE in sources_used:
        status = "FALLBACK_ONLY"
    else:
        status = "NO_METRICS"

    return MetricResolution(
        metrics=resolved,
        provenance=provenance,
        consistency={
            "status": status,
            "source_priority": list(SOURCE_PRIORITY),
            "sources_used": sources_used,
            "warnings": warnings,
            "blocked_candidates": blocked,
        },
    )
