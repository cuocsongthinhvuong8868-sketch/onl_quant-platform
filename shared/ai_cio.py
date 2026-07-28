import csv
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
import pandas as pd
import streamlit as st
from openai import OpenAI
from scipy.stats import percentileofscore
from config import DATA_LAKE, ROOT_DIR, AI_MODEL, AI_TEMPERATURE
from shared.ai_cio_metric_contract import append_direct_metrics as _append_direct_metrics
from shared.ai_cio_metric_contract import resolve_tool_metrics

# ── History CSV (Ai_cio_report.csv) ──
# Score/stress regime plus the independent capitulation phase gate.
# Older schemas are auto-migrated on the next write.
CSV_HISTORY_PATH = DATA_LAKE / "Ai_cio_report.csv"
CSV_HISTORY_HEADER = [
    "ddmmyyyy",
    "score",
    "regime",
    "source",
    "provider",
    "stress_regime",
    "capitulation_phase",
    "capitulation_action_eligible",
]
AI_CIO_HISTORY_PROVIDER = "deepseek-v4-pro"
AI_CIO_METRICS_VERSION = "3.0"
AI_CIO_HISTORY_WINDOW = 30
AI_CIO_METRICS_DIRNAME = "ai_cio_metrics"
HUMILITY_RULES_PREFIX = "ai_cio_humility_rules"
NON_SCORING_EVIDENCE_TOOLS = frozenset({"humility_falsification", "capitulation_regime"})
TELEGRAM_SUMMARY_PREFIX = "telegram_summary"
TELEGRAM_SUMMARY_CHAR_LIMIT = 3500
AI_CIO_CACHE_VERSION_HEADER = "ai-cio-cache-version"
AI_CIO_TOOL_CACHE_VERSIONS: dict[str, str] = {
    "feargreed": "fear_greed_v2_prompt_shock_overlay",
    "global_financial_conditions": "indicator_pr3y_pca_point_in_time_v1",
    "credit_spread": "primary_issuance_equal_weight_v1",
    "vnibor": "structured_20d_trend_v1",
    "vn100_earnings_health": "structured_yoy_v1",
    "esr_monitor": "production_downside_ema20_v1",
    "manipulation": "manipulation_v2_vnindex_prompt_guardrail",
    "dispersion": "dispersion_v2_broad_stress_prompt",
    "va_res": "vares_v2_prior_window_prompt",
    "upside_ratio": "upside_ratio_v2_stress_prompt",
    "var_cvar_vnindex": "var_cvar_vnindex_v3_prior_window_prompt",
    "sentiment_factor_news": "weighted_bayesian_posterior_social_overlay_v2",
    "executive_summary": "ai_cio_methodology_v6_updated_tool_prompt_discipline",
}
TOOL_METHODOLOGY_CARDS: dict[str, dict[str, str]] = {
    "fed_liquidity": {
        "domain": "global_liquidity",
        "horizon": "4-12_weeks",
        "primary_metric": "net_liquidity_impulse",
        "score_direction": "Higher is safer / more supportive.",
        "limits": "Liquidity quality matters; emergency balance-sheet expansion is not automatically bullish.",
        "authority": "Use structured metrics and adapter/decision_state when present; do not relabel from prose alone.",
    },
    "global_financial_conditions": {
        "domain": "external_credit_and_macro_stress",
        "horizon": "4-12_weeks",
        "primary_metric": "cqs_percentile_3y_and_point_in_time_pc1",
        "score_direction": "Higher 3Y CQS percentile is worse for risk assets.",
        "limits": "Indicator percentiles are 3Y max with 1Y warm-up; PC1 regime percentile remains 1Y. PCA is expanding point-in-time with periodic refits; no full-history PCA backfit or look-ahead revision. Do not offset high credit stress with short-term news sentiment.",
        "authority": "Adapter score/regime/bias are authoritative when available.",
    },
    "credit_spread": {
        "domain": "domestic_primary_credit_risk_premium",
        "horizon": "weeks_to_months",
        "primary_metric": "real_estate_minus_bank_primary_issuance_yield_bps",
        "score_direction": "Higher and widening real-estate risk premium is worse for domestic risk assets.",
        "limits": "Primary-issuance fixed-coupon sample only; issuer mix, maturity mix and missing floating coupons can move the spread. It is not secondary-market OAS or default probability.",
        "authority": "Use canonical equal-weight/all-maturity structured metrics and deterministic adapter; AI prose is supporting interpretation only.",
    },
    "margin_m2_overlay": {
        "domain": "speculative_leverage_overlay",
        "horizon": "monthly_lagged",
        "primary_metric": "margin_debt_to_m2_zscore",
        "score_direction": "Higher leverage crowding is worse when other stress tools are weak.",
        "limits": "Monthly overlay only; never a standalone regime switch.",
        "authority": "Use as amplification/discount context, not as a hard score driver unless adapter exists.",
    },
    "vnibor": {
        "domain": "domestic_funding_liquidity",
        "horizon": "1-4_weeks",
        "primary_metric": "overnight_rate_and_20_session_stress",
        "score_direction": "Higher/stickier funding stress is worse.",
        "limits": "Single-day easing does not neutralize a stressed 20-session trend.",
        "authority": "Adapter score/regime/bias are authoritative when available.",
    },
    "ltmm": {
        "domain": "liquidity_transmission",
        "horizon": "1-8_weeks",
        "primary_metric": "upstream_downstream_transmission_state",
        "score_direction": "Cleaner transmission is safer.",
        "limits": "Treat as transmission context, not a standalone crash signal.",
        "authority": "Use structured state if present; otherwise cite as soft interpretation.",
    },
    "vn100_corporate_health": {
        "domain": "bottom_up_fundamental_health",
        "horizon": "quarterly",
        "primary_metric": "vn100_health_score_and_breadth",
        "score_direction": "Higher health score and breadth are safer.",
        "limits": "Not a short-term timing tool; can diverge from price-based internals.",
        "authority": "Use as confidence and internal-quality overlay, not as a direct market-timing override.",
    },
    "humility_falsification": {
        "domain": "thesis_audit",
        "horizon": "current_vs_prior_rules",
        "primary_metric": "triggered_falsification_rules",
        "score_direction": "Fewer active falsification triggers preserve thesis confidence.",
        "limits": "Does not create a new thesis; it audits the previous one.",
        "authority": "If WATCH/FALSIFIED, discuss explicitly in trend and confidence.",
    },
    "fear_greed": {
        "domain": "sentiment_and_positioning",
        "horizon": "days_to_weeks",
        "primary_metric": "risk_score_from_point_in_time_pca_factors",
        "score_direction": "Higher score is safer / more risk-on, unless extreme greed is flagged.",
        "limits": "Factor PCA is expanding point-in-time; sentiment is secondary to hard liquidity, breadth, and tail-risk constraints.",
        "authority": "Use adapter score if available; otherwise treat as soft sentiment evidence.",
    },
    "manipulation": {
        "domain": "index_coupling_and_concentration",
        "horizon": "days_to_weeks",
        "primary_metric": "vingroup_to_vnindex_slope_percentile",
        "score_direction": "Higher coupling/concentration stress is worse.",
        "limits": "Measures cash-index coupling, not a direct VN30F1M/futures trade signal; do not overrule broad systemic tools alone.",
        "authority": "Use as concentration risk overlay unless adapter provides a hard score.",
    },
    "dispersion": {
        "domain": "market_structure_and_participation_quality",
        "horizon": "days_to_weeks",
        "primary_metric": "dispersion_pressure_index_with_broad_stress_overlay",
        "score_direction": "Health depends on whether dispersion is idiosyncratic or broad selloff stress.",
        "limits": "Low spread can still be dangerous when CSAD/CSSD and downside participation are extreme.",
        "authority": "Use as diagnostic market-internal evidence; confirm broad stress with breadth, ESR, VaRES, and Fear & Greed.",
    },
    "upside_ratio": {
        "domain": "upside_participation",
        "horizon": "days_to_weeks",
        "primary_metric": "upside_participation_ratio",
        "score_direction": "Higher sustained upside participation is safer.",
        "limits": "Monte Carlo projections are deterministic/reproducible with fixed seeds and are scenario diagnostics, not independent allocation authority. Zombie rallies without breadth confirmation should not lift regime materially.",
        "authority": "Use as internal participation evidence; do not overrule breadth/tail caps.",
    },
    "bank_valuation": {
        "domain": "sector_valuation",
        "horizon": "weeks_to_months",
        "primary_metric": "valuation_gap_and_quality_flags",
        "score_direction": "Undervalued plus quality confirmation is supportive.",
        "limits": "Cheap banks are not buy signals when market regime forbids equity risk.",
        "authority": "Use only with Risk-Adjusted Growth for stock selection.",
    },
    "market_breadth": {
        "domain": "market_internal_participation",
        "horizon": "days_to_weeks",
        "primary_metric": "breadth_ma20_pct",
        "score_direction": "Higher breadth is safer / healthier.",
        "limits": "Weak breadth caps bullish interpretation even if news or valuation is supportive.",
        "authority": "Adapter score/regime/bias are authoritative.",
    },
    "esr_monitor": {
        "domain": "systemic_stress",
        "horizon": "days_to_weeks",
        "primary_metric": "ssi_pct",
        "score_direction": "Higher SSI is worse.",
        "limits": "Tail-risk override dominates allocation; do not soften with valuation alone.",
        "authority": "Adapter score/regime/bias are authoritative.",
    },
    "va_res": {
        "domain": "contagion_and_complacency",
        "horizon": "days_to_weeks",
        "primary_metric": "prior_window_var_es_contagion_and_complacency",
        "score_direction": "Higher contagion/complacency stress is worse.",
        "limits": "Complacency low does not mean market safe; use stress index for active selloff and valid-name denominators for breadth.",
        "authority": "Use as tail-risk evidence; v2 regime and valid denominators are authoritative when present.",
    },
    "var_cvar_vnindex": {
        "domain": "left_tail_risk",
        "horizon": "days_to_weeks",
        "primary_metric": "prior_window_var_es_evt_xi_threshold_sensitivity",
        "score_direction": "Higher EVT xi is worse.",
        "limits": "VaR/ES uses prior-window returns; EVT threshold sensitivity and MCMC intervals are robustness/confidence diagnostics, not second bearish votes.",
        "authority": "Use tail_regime and robust-threshold fields when present; hard cap only when xi is robust across thresholds.",
    },
    "sentiment_factor_news": {
        "domain": "news_sentiment",
        "horizon": "1-3_days",
        "primary_metric": "news_sentiment_factor_with_source_counts",
        "score_direction": "More positive news is supportive only at short horizon.",
        "limits": "Short-term noise; mozyfin_social is lower-confidence social/opinion evidence and cannot veto macro, funding, breadth, or tail-risk stress.",
        "authority": "Use as soft overlay unless hard adapter exists; discount signal strength when source_counts is dominated by mozyfin_social.",
    },
    "risk_adjusted_growth": {
        "domain": "bank_growth_quality",
        "horizon": "weeks_to_months",
        "primary_metric": "economic_alpha",
        "score_direction": "Higher economic alpha is better for stock selection.",
        "limits": "Stock-picking tool only; cannot override low AI CIO allocation regime.",
        "authority": "Use with Bank Valuation for bank picks; not a market-regime override.",
    },
    "pvgo": {
        "domain": "valuation_expectation_risk",
        "horizon": "medium_term",
        "primary_metric": "pvgo_pct",
        "score_direction": "Higher PVGO means more embedded growth expectation risk.",
        "limits": "Not a crash timing signal; stale valuation feed is DATA INSUFFICIENT and cannot raise confidence.",
        "authority": "Adapter score/regime/bias are authoritative; do not relabel from raw PVGO pct.",
    },
    "abm_simulator": {
        "domain": "abm_v4_pre_shock_early_warning_and_margin_cascade",
        "horizon": "days_to_weeks",
        "primary_metric": "early_warning_score_and_level",
        "score_direction": "Higher early-warning score is worse; YELLOW/ORANGE/RED reduce risk budget. Distance, panic, leverage, and cascade vulnerability are supporting diagnostics.",
        "limits": "Pre-shock stress diagnostic, not an exact crash-timing model and not a standalone buy/sell signal.",
        "authority": "ABM v4 early_warning_score/level and adapter score/regime/bias are authoritative when ABM CSV metrics are available.",
    },
    "capitulation_regime": {
        "domain": "price_path_capitulation_phase_gate",
        "horizon": "sessions_to_weeks",
        "primary_metric": "three_gate_climax_then_exhaustion_confirmation",
        "score_direction": "Gate-only state; its uncalibrated evidence scores are not probabilities or composite-score inputs.",
        "limits": "FRAGILE, LIQUIDATION and CAPITULATION_CLIMAX are not bottom signals. Only action-eligible EXHAUSTION_CONFIRMED can activate the CAPITULATION decision override.",
        "authority": "Deterministic phase/action_eligible are authoritative for capitulation policy; the LLM cannot relabel them.",
    },
}
HUMILITY_DEFAULT_RULES = [
    {
        "model": "VNIBOR Monitor",
        "metric": "STRESS/WARNING sessions (20D)",
        "threshold_operator": "<",
        "threshold_value": 5,
        "unit": "sessions",
        "description": "Liquidity pressure is no longer persistent if stressed funding sessions fall below 5 of the last 20 observations.",
    },
    {
        "model": "Market Breadth",
        "metric": "Breadth MA20",
        "threshold_operator": ">",
        "threshold_value": 45,
        "unit": "%",
        "description": "Internal participation materially improves when more than 45% of covered tickers trade above MA20.",
    },
    {
        "model": "ESR Monitor",
        "metric": "Systemic Stress Index (SSI)",
        "threshold_operator": "<",
        "threshold_value": 55,
        "unit": "%",
        "description": "Systemic stress cools if SSI drops below 55%.",
    },
    {
        "model": "Tail Risk (EVT)",
        "metric": "EVT Xi Max (5%-15% thresholds)",
        "threshold_operator": "<",
        "threshold_value": 0.25,
        "unit": "",
        "description": "Left-tail risk normalizes only when the upper sensitivity bound xi_max falls below 0.25.",
    },
    {
        "model": "Manipulation / Coupling",
        "metric": "Vingroup Slope Percentile",
        "threshold_operator": "<",
        "threshold_value": 70,
        "unit": "th pct",
        "description": "Index coupling risk eases when the Vingroup slope percentile falls below the 70th percentile.",
    },
    {
        "model": "Global Financial Conditions",
        "metric": "CQS Percentile",
        "threshold_operator": "<",
        "threshold_value": 80,
        "unit": "th pct",
        "description": "External credit-quality stress eases when CQS drops below the 80th percentile.",
    },
]


def parse_score_regime(report_text: str) -> tuple:
    """Parse score/regime from an AI CIO report."""
    if not report_text:
        return "N/A", "N/A"

    strict = re.compile(
        r"final\s+score\s*&\s*regime\s*[:=]\s*([-+]?\d+(?:\.\d+)?)"
        r"\s*;\s*regime\s*[:=]\s*([^\n`]+)",
        re.IGNORECASE,
    )
    matches = list(strict.finditer(report_text))
    if matches:
        match = matches[-1]
        return match.group(1), _clean_regime_value(match.group(2))

    lines = report_text.strip().splitlines()
    score_val, regime_val = "N/A", "N/A"
    tail = lines[-80:]
    for i, line in enumerate(tail):
        score_match = re.search(
            r"final\s+score(?:\s*&\s*regime)?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
            line,
            re.IGNORECASE,
        )
        if not score_match:
            continue
        score_val = score_match.group(1)

        same_line = re.search(r";\s*regime\s*[:=]\s*([^\n`]+)", line, re.IGNORECASE)
        if same_line:
            regime_val = _clean_regime_value(same_line.group(1))
            continue

        for candidate in tail[i + 1 : i + 4]:
            regime_match = re.search(r"^\s*(?:[-*]\s*)?regime\s*[:=]\s*([^\n`]+)", candidate, re.IGNORECASE)
            if regime_match:
                regime_val = _clean_regime_value(regime_match.group(1))
                break

    if score_val != "N/A" and regime_val != "N/A":
        return score_val, regime_val

    score_fallback = _parse_summary_score(report_text)
    regime_fallback = _parse_summary_regime(report_text)
    if score_fallback != "N/A":
        score_val = score_fallback
    if regime_fallback != "N/A":
        regime_val = regime_fallback
    return score_val, regime_val


def _clean_regime_value(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", str(value))
    cleaned = cleaned.replace("**", "").replace("`", "").strip()
    split = re.split(r"\bregime\s*[:=]\s*", cleaned, flags=re.IGNORECASE)
    if len(split) > 1:
        cleaned = split[-1].strip()
    return cleaned.strip(" .;:-")


def _parse_summary_score(report_text: str) -> str:
    patterns = [
        r"Composite Score\)\*\*\s*:\s*([-+]?\d+(?:\.\d+)?)\s*/\s*100",
        r"Composite Score\s*[:=]\s*([-+]?\d+(?:\.\d+)?)\s*/?\s*100?",
        r"Điểm\s+số\s+tổng\s+hợp.*?([-+]?\d+(?:\.\d+)?)\s*/\s*100",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, report_text, flags=re.IGNORECASE)
        if matches:
            return str(matches[-1])
    return "N/A"


def _parse_summary_regime(report_text: str) -> str:
    patterns = [
        r"Regime\)\*\*\s*:\s*([^\n]+)",
        r"Trạng\s+thái\s+vĩ\s+mô.*?\*\*\s*:\s*([^\n]+)",
        r"Macro Regime\s*[:=]\s*([^\n]+)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, report_text, flags=re.IGNORECASE)
        if matches:
            return _clean_regime_value(matches[-1])
    return "N/A"


def upsert_history_csv(
    score_val: str,
    regime_val: str,
    source: str = "manual",
    provider: str = "",
    target_date: date = None,
    stress_regime: str = "",
    capitulation_phase: str = "",
    capitulation_action_eligible: bool | None = None,
) -> bool:
    """Upsert score, resolved regime, and independent capitulation phase history.

    Logic same-day:
    - Nếu file đã có row cùng ngày → **ghi đè** (drop row cũ, thêm row mới)
    - Nếu chưa → append vào cuối

    `source` ∈ {"manual", "auto"} để track xuất xứ. Khi user chủ động chạy AI CIO
    từ app, nó sẽ overwrite kết quả AUTO cùng ngày (semantic: user trust > cron).

    Backwards-compat: nếu CSV cũ thiếu cột source/provider → fill empty string,
    rewrite với header mới đầy đủ.

    Trả True nếu ghi thành công, False nếu score/regime invalid.
    """
    if provider != AI_CIO_HISTORY_PROVIDER:
        print(
            f"[CSV] Skip history upsert: provider={provider} is not "
            f"{AI_CIO_HISTORY_PROVIDER}."
        )
        return False

    if not score_val or score_val == "N/A":
        return False

    if target_date is None:
        target_date = date.today()
    target_ddmmyyyy = target_date.strftime('%d%m%Y')

    rows = []
    if CSV_HISTORY_PATH.exists():
        try:
            with open(CSV_HISTORY_PATH, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('ddmmyyyy') == target_ddmmyyyy:
                        continue  # drop row cùng ngày → upsert
                    # Backwards-compat: fill missing fields
                    for field in CSV_HISTORY_HEADER:
                        if field not in row:
                            row[field] = ""
                    rows.append(row)
        except Exception as exc:
            print(f"[CSV] Warning: đọc file cũ thất bại ({exc}), tạo mới.")
            rows = []

    rows.append({
        'ddmmyyyy': target_ddmmyyyy,
        'score': score_val,
        'regime': regime_val,
        'source': source,
        'provider': provider,
        'stress_regime': stress_regime,
        'capitulation_phase': capitulation_phase,
        'capitulation_action_eligible': (
            ""
            if capitulation_action_eligible is None
            else str(capitulation_action_eligible).lower()
        ),
    })

    CSV_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_HISTORY_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HISTORY_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    return True
try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {
            "display": "Kimi 2.6",
            "api_model": "kimi-k2.6",
            "base_url": "https://api.moonshot.ai/v1",
        },
        "kimi-2.6-local": {
            "display": "Kimi 2.6 Local",
            "api_model": "kimi-k2.6",
            "base_url": "http://127.0.0.1:5001/v1",
            "temperature": 0.4,
            "timeout": 600,
        },
        "chatgpt-local": {
            "display": "ChatGPT Local",
            "api_model": "gpt-5.5",
            "base_url": "http://127.0.0.1:5003/v1",
            "temperature": 0.2,
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
from shared.data_loader import load_close_prices, load_custom, load_volumes

# Import logic Fear Greed
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import METHOD_VERSION as FEAR_GREED_METHOD_VERSION, calculate_risk_score
from tools.upside_ratio.quant.metrics import build_breadth_series, summarize_breadth_state
from tools.upside_ratio.quant.engine import DEFAULT_MC_SEED, run_hybrid_ensemble_mc
# Import logic Manipulation
from tools.manipulation.quant.engine import (
    METHOD_VERSION as MANIPULATION_METHOD_VERSION,
    TARGET as MANIPULATION_TARGET,
    prepare_data as prep_mani,
    compute_metrics as comp_mani,
    classify_regime,
)
# Import logic Dispersion
from tools.dispersion.quant.metrics import (
    calculate_dispersion_metrics,
    determine_macro_regime,
    fit_rolling_correlation,
    summarize_dispersion_state,
)
# Import logic Upside Ratio

# Import logic Bank Valuation
from tools.bank_valuation.quant.engine.ai_analysis import build_bank_valuation_ai_prompt
from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime
from tools.bank_valuation.quant.pipeline import run_bank_valuation_pipeline
# Import logic Sentiment Factor From News
from tools.sentiment_factor_news.report import build_sentiment_factor_news_ai_prompt
from tools.sentiment_factor_news.report import snapshot as sentiment_factor_news_snapshot
# Import logic PVGO Valuation
from tools.pvgo.report import build_ai_cio_context as build_pvgo_ai_cio_context
from tools.pvgo.report import snapshot as pvgo_snapshot
# Import logic Market Breadth
from tools.market_breadth.quant.metrics import compute_breadth, top10_by_volume
# Import logic ESR Monitor
from tools.esr_monitor.quant.metrics import (
    run_esr_pipeline, VN30_TICKERS,
    PRODUCTION_DEPOSIT_RATE, PRODUCTION_PILLAR_MODE, PRODUCTION_PCA_WARMUP,
    PRODUCTION_EMA_SPAN, PRODUCTION_REGIME_METHOD,
)
# Import logic VaRES Engine
from tools.va_res.report import snapshot as vares_snapshot
# Import logic Var-CVaR VNINDEX
from tools.var_cvar_vnindex.report import snapshot as var_cvar_snapshot
# Import Humility/Falsification audit context
from tools.humility_falsification.page import get_humility_falsification_context
from tools.capitulation_regime import METHODOLOGY_VERSION as CAPITULATION_METHODOLOGY_VERSION
from tools.capitulation_regime import analyze_capitulation
from shared.ai_cio_scoring import derive_metric_implied_scores, regime_from_score, score_tool_packet

def _get_cache_path(tool_name: str, provider_key: str = "kimi-2.6") -> str:
    today_str = date.today().strftime('%d%m%y')
    return DATA_LAKE / "daily_cache" / f"{tool_name}_{provider_key}_{today_str}.txt"


def _cache_version_for_tool(tool_name: str) -> str | None:
    return AI_CIO_TOOL_CACHE_VERSIONS.get(str(tool_name or ""))


def strip_wrapping_markdown_fence(report_text: str) -> str:
    """Remove a whole-report Markdown/text code fence returned by some LLMs."""

    text = str(report_text or "").strip()
    if not text:
        return ""

    header = ""
    header_pattern = (
        rf"^\s*(<!--\s*{re.escape(AI_CIO_CACHE_VERSION_HEADER)}\s*:\s*[^>]+-->)\s*"
    )
    header_match = re.match(header_pattern, text, flags=re.IGNORECASE)
    if header_match:
        header = header_match.group(1).strip() + "\n"
        body = text[header_match.end():].lstrip()
    else:
        body = text

    opening = re.match(r"^```(?:markdown|md|text)?[ \t]*(?:\r?\n|$)", body, flags=re.IGNORECASE)
    if not opening:
        return text
    if not re.search(r"(?:\r?\n)?```[ \t]*$", body):
        return text

    body = body[opening.end():]
    body = re.sub(r"\s*```[ \t]*$", "", body).strip()
    return (header + body).strip()


def _encode_cache_content(tool_name: str, content: str) -> str:
    version = _cache_version_for_tool(tool_name)
    text = str(content or "")
    if not version:
        return text
    marker = f"<!-- {AI_CIO_CACHE_VERSION_HEADER}: {version} -->\n"
    if text.startswith(marker):
        return text
    return marker + text


def _decode_cache_content(tool_name: str, content: str) -> str | None:
    text = str(content or "")
    expected = _cache_version_for_tool(tool_name)
    if not expected:
        return text
    match = re.match(
        rf"^\s*<!--\s*{re.escape(AI_CIO_CACHE_VERSION_HEADER)}\s*:\s*([^>]+?)\s*-->\s*",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    if match.group(1).strip() != expected:
        return None
    decoded = text[match.end():].lstrip("\r\n")
    if str(tool_name or "") == "executive_summary":
        decoded = strip_wrapping_markdown_fence(decoded)
    return decoded


def _read_cache_file(path: Path, tool_name: str) -> str | None:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return _decode_cache_content(tool_name, f.read())
    return None


def _read_cache(tool_name: str, provider_key: str = "kimi-2.6") -> str | None:
    path = _get_cache_path(tool_name, provider_key)
    if path.exists():
        return _read_cache_file(path, tool_name)
    return None


def _write_cache(tool_name: str, content: str, provider_key: str = "kimi-2.6"):
    path = _get_cache_path(tool_name, provider_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_encode_cache_content(tool_name, content))


def _get_humility_rules_path(provider_key: str, target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{HUMILITY_RULES_PREFIX}_{provider_key}_{date_key}.json"


def get_telegram_summary_path(provider_key: str, target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{TELEGRAM_SUMMARY_PREFIX}_{provider_key}_{date_key}.txt"


def get_ai_cio_context_path(provider_key: str, target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"ai_cio_context_{provider_key}_{date_key}.json"


def _read_ai_cio_context_for_summary(provider_key: str, target_date: date) -> str:
    """Read a compact structured context block for Telegram summarization."""
    path = get_ai_cio_context_path(provider_key, target_date)
    if not path.exists():
        return "STRUCTURED_CONTEXT_UNAVAILABLE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"STRUCTURED_CONTEXT_ERROR: {exc}"

    decision_state = payload.get("decision_state") or {}
    metrics_snapshot = payload.get("metrics_snapshot") or {}
    metrics_snapshot_path = payload.get("metrics_snapshot_path")
    if not metrics_snapshot:
        candidate_path = _get_ai_cio_metrics_snapshot_path(target_date, provider_key)
        if not candidate_path.exists():
            candidate_path = _get_ai_cio_metrics_snapshot_path(target_date)
        if candidate_path.exists():
            try:
                metrics_snapshot = json.loads(candidate_path.read_text(encoding="utf-8"))
                metrics_snapshot_path = str(candidate_path)
            except Exception:
                metrics_snapshot = {}
    snapshot_history = metrics_snapshot.get("history") if isinstance(metrics_snapshot, dict) else {}
    tool_scores = decision_state.get("tool_scores") or []
    compact = {
        "metric_implied_score": decision_state.get("metric_implied_score"),
        "metric_implied_regime": decision_state.get("metric_implied_regime"),
        "baseline_stress_regime": decision_state.get("baseline_stress_regime"),
        "baseline_resolved_regime": decision_state.get("baseline_resolved_regime"),
        "stress_regime": decision_state.get("stress_regime"),
        "resolved_regime": decision_state.get("resolved_regime"),
        "capitulation_state": decision_state.get("capitulation_state"),
        "allocation_guardrail": decision_state.get("allocation_guardrail"),
        "metric_implied_subscores": decision_state.get("metric_implied_subscores"),
        "tool_score_count": decision_state.get("tool_score_count"),
        "tool_scores": tool_scores[:8],
        "hard_constraints": decision_state.get("hard_constraints"),
        "score_band_reason": decision_state.get("score_band_reason"),
        "previous_cio_diagnostic": decision_state.get("previous_cio_diagnostic"),
        "history_rolling_summary": (snapshot_history or {}).get("rolling_summary"),
        "metrics_snapshot_path": metrics_snapshot_path,
    }
    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def summarize_executive_report_for_telegram(
    api_key: str,
    report_text: str,
    provider_key: str = "deepseek-v4-pro",
    report_date: date | None = None,
    force: bool = False,
) -> str:
    """Create a short Telegram-ready AI CIO brief and cache it by report date."""

    target_date = report_date or _parse_report_date_from_text(report_text) or date.today()
    cache_path = get_telegram_summary_path(provider_key, target_date)
    score_val, regime_val = parse_score_regime(report_text)
    if cache_path.exists() and not force:
        cached = cache_path.read_text(encoding="utf-8").strip()
        cleaned = _clean_telegram_summary(cached, target_date, score_val, regime_val)
        if cleaned != cached:
            cache_path.write_text(cleaned, encoding="utf-8")
        return cleaned

    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["deepseek-v4-pro"])
    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))
    model = cfg["api_model"]
    temperature = 0.0
    structured_context = _read_ai_cio_context_for_summary(provider_key, target_date)

    system_prompt = (
        "You are a portfolio risk chief writing a concise Vietnamese Telegram brief. "
        "Compress the AI CIO report into an action-oriented daily decision note. "
        "Use only facts in the report. Do not add prices or new tickers. "
        "When STRUCTURED DECISION CONTEXT is available, use metric_implied_score, "
        "tool_scores, hard_constraints, and score_band_reason as the authoritative "
        "source for the Overlay line and key drivers. "
        "If the report contains section 5.5 LLM Overlay, explicitly summarize the "
        "metric-implied score, overlay adjustment, and final CIO score in one line. "
        "Never include source-report delimiters or a copied section of the full report. "
        "Keep the output under 2300 Vietnamese characters. Plain text only; no Markdown tables, no JSON."
    )
    user_prompt = f"""
REPORT DATE: {target_date.strftime('%d/%m/%Y')}
PARSED SCORE: {score_val}
PARSED REGIME: {regime_val}

STRUCTURED DECISION CONTEXT:
{structured_context}

Write exactly this structure:
AI CIO DAILY BRIEF - DD/MM/YYYY
Score/Regime: <score>/100 - <regime>
Overlay: <metric-implied score/regime> | <overlay adjustment> | <final CIO score/regime>
Allocation: Cash X% | Equity Y% | Hedge Z%
Verdict: <1 compact sentence>
Key drivers:
- <driver 1 with number>
- <driver 2 with number>
- <driver 3 with number>
Action:
- <portfolio action 1>
- <portfolio action 2>
- <risk trigger to monitor>
Humility check: <INTACT/WATCH/FALSIFIED if available, plus 1 sentence>

SOURCE REPORT BELOW. Use it only as input. Do not quote, copy, or include this section in your answer.
<source_report>
{report_text}
</source_report>
""".strip()

    summary = call_ai(client, system_prompt, user_prompt, model=model, temperature=temperature)
    summary = _clean_telegram_summary(summary, target_date, score_val, regime_val)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(summary, encoding="utf-8")
    return summary


def _clean_telegram_summary(summary: str, target_date: date, score_val: str, regime_val: str) -> str:
    text = (summary or "").strip()
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = _strip_telegram_source_echo(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        text = (
            f"AI CIO DAILY BRIEF - {target_date.strftime('%d/%m/%Y')}\n"
            f"Score/Regime: {score_val}/100 - {regime_val}\n"
            "Verdict: Summary unavailable; read full AI CIO report."
        )
    if len(text) > TELEGRAM_SUMMARY_CHAR_LIMIT:
        text = text[: TELEGRAM_SUMMARY_CHAR_LIMIT - 80].rstrip()
        text += "\n\n[Trimmed for Telegram. Read full report for details.]"
    return text


def _strip_telegram_source_echo(text: str) -> str:
    """Remove source report content if the model echoes prompt input into Telegram output."""

    if not text:
        return ""

    source_markers = [
        r"(?im)^\s*Full AI CIO report\s*:\s*",
        r"(?im)^\s*SOURCE REPORT BELOW\b.*",
        r"(?im)^\s*<source_report\b[^>]*>\s*",
    ]
    cut_points = [
        match.start()
        for pattern in source_markers
        if (match := re.search(pattern, text))
    ]
    if not cut_points:
        return text
    return text[: min(cut_points)].rstrip()


def postprocess_executive_summary_report(
    report_text: str,
    provider_key: str,
    decision_state: dict[str, Any] | None = None,
) -> tuple[str, Path | None]:
    """Strip the machine JSON block from the human report and save it as a sidecar file."""

    source_text = strip_wrapping_markdown_fence(report_text)
    if decision_state is not None:
        source_text = _enforce_final_score_regime(source_text, decision_state)
    payload, span = _extract_falsification_payload(source_text)
    clean_text = source_text
    if span is not None:
        clean_text = f"{source_text[:span[0]].rstrip()}\n\n{source_text[span[1]:].lstrip()}".strip()
    elif '"falsification_rules"' in source_text:
        clean_text = _strip_incomplete_falsification_block(source_text)

    if payload is None and '"falsification_rules"' in source_text:
        payload = _fallback_humility_payload_from_markdown(clean_text)

    score_val, regime_val = parse_score_regime(clean_text)
    if score_val == "N/A" and payload:
        score_val = _payload_number_as_text(payload.get("composite_score"))
    if regime_val == "N/A" and payload:
        regime_val = _clean_regime_value(str(payload.get("regime", ""))) or "N/A"
    if score_val == "N/A" or regime_val == "N/A":
        fallback_score, fallback_regime = parse_score_regime(source_text)
        if score_val == "N/A":
            score_val = fallback_score
        if regime_val == "N/A":
            regime_val = fallback_regime

    if score_val != "N/A" and regime_val != "N/A" and not _has_final_score_line(clean_text):
        clean_text = clean_text.rstrip() + f"\n\nfinal score & regime : {score_val} ; regime : {regime_val}\n"

    if decision_state is not None:
        clean_text = _enforce_final_score_regime(clean_text, decision_state)
        enforced_score, enforced_regime = parse_score_regime(clean_text)
        if enforced_score != "N/A":
            score_val = enforced_score
        if enforced_regime != "N/A":
            regime_val = enforced_regime

    if payload:
        if score_val != "N/A":
            payload["composite_score"] = float(score_val)
        if regime_val != "N/A":
            payload["regime"] = regime_val
    sidecar_path = _write_humility_rules_payload(payload, provider_key) if payload else None

    return clean_text, sidecar_path


def _score_band_for_regime(regime: str) -> tuple[int, int] | None:
    normalized = _clean_regime_value(regime).upper()
    if normalized == "CAPITULATION":
        # Capitulation is a path-dependent phase override, not a score band.
        return None
    if normalized == "EXTREME CRISIS":
        return 0, 14
    if normalized == "PRE-CRASH / PANIC":
        return 15, 29
    if normalized == "FEAR / DISTRIBUTION":
        return 30, 44
    if normalized == "NEUTRAL / STOCK-PICKING":
        return 45, 59
    if normalized == "UPTREND / EXPANSION":
        return 60, 74
    if normalized == "BULL CONFIRMED":
        return 75, 89
    if normalized == "EXTREME GREED / TOP WARNING":
        return 90, 100
    return None


def _capitulation_action_eligible(decision_state: dict[str, Any] | None) -> bool:
    """Fail closed unless exhaustion is confirmed with usable detector data."""
    if not isinstance(decision_state, dict):
        return False

    state: Any = decision_state.get("capitulation_state")
    if hasattr(state, "to_dict"):
        state = state.to_dict()
    if not isinstance(state, dict):
        return False

    phase = state.get("phase")
    if hasattr(phase, "value"):
        phase = phase.value
    if str(phase or "").strip().upper() != "EXHAUSTION_CONFIRMED":
        return False

    explicit_eligibility = state.get("action_eligible")
    if explicit_eligibility is not True:
        return False

    data_quality: Any = state.get("data_quality")
    if hasattr(data_quality, "to_dict"):
        data_quality = data_quality.to_dict()
    if isinstance(data_quality, dict):
        quality_status = data_quality.get("status")
    else:
        quality_status = getattr(data_quality, "status", None)
    if str(quality_status or "").strip().upper() not in {"GOOD", "LIMITED"}:
        return False

    freshness_status = state.get("freshness_status")
    if str(freshness_status or "").strip().upper() != "CURRENT":
        return False
    return True


def _enforce_final_score_regime(
    report_text: str,
    decision_state: dict[str, Any] | None,
) -> str:
    """Resolve the final regime deterministically while preserving its canonical line."""
    if not report_text:
        return report_text

    score_value, _ = parse_score_regime(report_text)
    final_score = _safe_float(score_value)
    if final_score is None and isinstance(decision_state, dict):
        final_score = _safe_float(
            decision_state.get("final_score", decision_state.get("metric_implied_score"))
        )
    if final_score is None:
        return report_text
    final_score = max(0.0, min(100.0, final_score))

    expected_regime = (
        "CAPITULATION"
        if _capitulation_action_eligible(decision_state)
        else regime_from_score(final_score)
    )
    score_display = (
        f"{final_score:.0f}" if final_score.is_integer() else f"{final_score:.1f}"
    )
    score_pattern = re.compile(
        r"(?P<prefix>final\s+score\s*&\s*regime\s*[:=]\s*)"
        r"(?P<score>[-+]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    score_matches = list(score_pattern.finditer(report_text))
    if score_matches:
        score_match = score_matches[-1]
        report_text = (
            f"{report_text[:score_match.start('score')]}{score_display}"
            f"{report_text[score_match.end('score'):]}"
        )
    final_pattern = re.compile(
        r"(?P<prefix>final\s+score\s*&\s*regime\s*[:=]\s*[-+]?\d+(?:\.\d+)?"
        r"\s*;\s*regime\s*[:=]\s*)(?P<regime>[^\n`]+)",
        re.IGNORECASE,
    )
    matches = list(final_pattern.finditer(report_text))
    if matches:
        match = matches[-1]
        raw_regime = match.group("regime")
        clean_regime = _clean_regime_value(raw_regime)
        if clean_regime.upper() != expected_regime:
            # Retain surrounding Markdown emphasis and punctuation on the final line.
            token_start = raw_regime.lower().find(clean_regime.lower()) if clean_regime else -1
            if token_start >= 0:
                token_end = token_start + len(clean_regime)
                replacement = (
                    f"{raw_regime[:token_start]}{expected_regime}{raw_regime[token_end:]}"
                )
            else:
                replacement = expected_regime
            report_text = (
                f"{report_text[:match.start('regime')]}{replacement}"
                f"{report_text[match.end('regime'):]}"
            )
    else:
        report_text = (
            report_text.rstrip()
            + f"\n\nfinal score & regime : {score_display} ; regime : {expected_regime}\n"
        )

    canonical_regimes = sorted(
        {
            "CAPITULATION",
            "EXTREME CRISIS",
            "PRE-CRASH / PANIC",
            "FEAR / DISTRIBUTION",
            "NEUTRAL / STOCK-PICKING",
            "UPTREND / EXPANSION",
            "BULL CONFIRMED",
            "EXTREME GREED / TOP WARNING",
        },
        key=len,
        reverse=True,
    )
    regime_token = re.compile(
        "|".join(re.escape(value) for value in canonical_regimes),
        re.IGNORECASE,
    )
    structured_line = re.compile(
        r"(?im)^(?P<line>[^\n]*(?:Resolved\s+Regime|Final\s+CIO\s+score/regime\s+after\s+overlay)[^\n]*)$"
    )

    def normalize_structured_line(match: re.Match[str]) -> str:
        line = match.group("line")
        tokens = list(regime_token.finditer(line))
        if not tokens:
            return line
        token = tokens[-1]
        return f"{line[:token.start()]}{expected_regime}{line[token.end():]}"

    report_text = structured_line.sub(normalize_structured_line, report_text)
    canonical_line_pattern = re.compile(
        r"(?im)^\s*\**\s*final\s+score\s*&\s*regime\s*[:=]\s*"
        r"[-+]?\d+(?:\.\d+)?\s*;\s*regime\s*[:=][^\n`]+$"
    )
    canonical_lines = list(canonical_line_pattern.finditer(report_text))
    if canonical_lines:
        authoritative_line = canonical_lines[-1].group(0).strip()
        report_text = canonical_line_pattern.sub("", report_text)
        report_text = re.sub(r"\n{3,}", "\n\n", report_text).rstrip()
        report_text = f"{report_text}\n\n{authoritative_line}" if report_text else authoritative_line
    if isinstance(decision_state, dict):
        final_stress_regime = regime_from_score(final_score)
        decision_state["final_score"] = final_score
        decision_state["final_stress_regime"] = final_stress_regime
        decision_state["final_resolved_regime"] = expected_regime
        decision_state["stress_regime"] = final_stress_regime
        decision_state["resolved_regime"] = expected_regime
        decision_state["capitulation_override_active"] = expected_regime == "CAPITULATION"
    return report_text


def _normalized_ssi_fraction(value: Any) -> float | None:
    ssi = _safe_float(value)
    if ssi is None or ssi < 0:
        return None
    # The structured key is ``ssi_pct`` and is contractually in percentage points.
    return ssi / 100.0


def _extract_final_confidence(report_text: str) -> str | None:
    matches = list(
        re.finditer(
            r"(?im)^.*final\s+confidence\s*\*{0,2}\s*[:=]\s*\*{0,2}\s*"
            r"(low|medium|high)\b",
            report_text or "",
        )
    )
    return matches[-1].group(1).lower() if matches else None


def _allocation_policy_for_score(
    score: float,
    decision_state: dict[str, Any] | None,
) -> dict[str, Any]:
    capitulation_override = _capitulation_action_eligible(decision_state)
    if capitulation_override:
        max_equity, max_short = 20.0, 0.0
        label = "CAPITULATION phase override"
    elif score <= 14:
        max_equity, max_short = 0.0, 20.0
        label = "EXTREME CRISIS"
    elif score <= 29:
        max_equity, max_short = 15.0, 0.0
        label = "PRE-CRASH / PANIC"
    elif score <= 44:
        max_equity, max_short = 35.0, 0.0
        label = "FEAR / DISTRIBUTION"
    elif score <= 59:
        max_equity, max_short = 55.0, 0.0
        label = "NEUTRAL / STOCK-PICKING"
    elif score <= 74:
        max_equity, max_short = 75.0, 0.0
        label = "UPTREND / EXPANSION"
    elif score <= 89:
        max_equity, max_short = 95.0, 0.0
        label = "BULL CONFIRMED"
    else:
        max_equity, max_short = 85.0, 0.0
        label = "EXTREME GREED / TOP WARNING"
    base_max_equity = max_equity
    policy = {
        "label": label,
        "max_equity_pct": max_equity,
        "base_max_equity_pct": base_max_equity,
        "min_cash_pct": 100.0 - max_equity,
        "max_short_vn30f1m_pct": max_short,
        "capitulation_override": capitulation_override,
        "bottom_fishing_allowed": capitulation_override,
    }
    metrics = decision_state.get("metric_values") if isinstance(decision_state, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    ssi = _normalized_ssi_fraction(metrics.get("esr_monitor.ssi_pct"))
    evt_xi = _safe_float(metrics.get("var_cvar_vnindex.evt_xi"))
    evt_xi_min = _safe_float(metrics.get("var_cvar_vnindex.evt_xi_min"))
    score_band_reason = decision_state.get("score_band_reason") if isinstance(decision_state, dict) else None
    caps = score_band_reason.get("caps", []) if isinstance(score_band_reason, dict) else []
    robust_evt = (
        evt_xi is not None
        and evt_xi_min is not None
        and evt_xi > 0.30
        and evt_xi_min >= 0.30
    ) or any("robust" in str(cap).lower() and "evt" in str(cap).lower() for cap in (caps or []))

    tail_cap: float | None = None
    tail_reasons: list[str] = []
    if ssi is not None and ssi > 0.80:
        tail_cap = 30.0
        tail_reasons.append(f"SSI critical ({ssi:.2f})")
    if robust_evt:
        tail_cap = 30.0 if tail_cap is None else min(tail_cap, 30.0)
        tail_reasons.append("EVT xi robust above 0.30")
    if 60 <= score <= 74 and ssi is not None and ssi > 0.60:
        tail_cap = 60.0 if tail_cap is None else min(tail_cap, 60.0)
        tail_reasons.append(f"SSI elevated for expansion band ({ssi:.2f})")
    if 75 <= score <= 89 and ssi is not None and ssi > 0.60:
        tail_cap = 90.0 if tail_cap is None else min(tail_cap, 90.0)
        tail_reasons.append(f"tail risk elevated for bull band ({ssi:.2f})")
    if tail_cap is not None:
        policy["max_equity_pct"] = min(policy["max_equity_pct"], tail_cap)
        policy["tail_risk_cap_pct"] = tail_cap
        policy["tail_risk_reasons"] = tail_reasons
        policy["label"] += " + tail-risk cap"

    confidence = str(
        (decision_state or {}).get("final_confidence")
        or (decision_state or {}).get("confidence")
        or ""
    ).strip().lower() if isinstance(decision_state, dict) else ""
    if confidence == "low" and not capitulation_override:
        if score <= 14:
            confidence_cap = 0.0
        elif score <= 29:
            confidence_cap = 0.0
        elif score <= 44:
            confidence_cap = 15.0
        elif score <= 59:
            confidence_cap = 35.0
        elif score <= 74:
            confidence_cap = 55.0
        else:
            confidence_cap = 75.0
        policy["max_equity_pct"] = min(policy["max_equity_pct"], confidence_cap)
        policy["confidence_cap_pct"] = confidence_cap
        policy["label"] += " + LOW-confidence one-bracket reduction"
    baseline = decision_state.get("allocation_guardrail") if isinstance(decision_state, dict) else None
    if isinstance(baseline, dict):
        baseline_equity = _safe_float(baseline.get("max_equity_pct"))
        baseline_short = _safe_float(baseline.get("max_short_vn30f1m_pct"))
        if baseline_equity is not None:
            policy["max_equity_pct"] = min(policy["max_equity_pct"], baseline_equity)
        if baseline_short is not None:
            policy["max_short_vn30f1m_pct"] = min(
                policy["max_short_vn30f1m_pct"],
                baseline_short,
            )
        policy["label"] += " + deterministic baseline cap"
    policy["min_cash_pct"] = 100.0 - policy["max_equity_pct"]
    return policy


def _enforce_final_allocation_policy(
    report_text: str,
    decision_state: dict[str, Any] | None,
) -> str:
    """Clamp structured Executive Order sleeves to deterministic policy maxima."""

    if not report_text:
        return report_text
    report_text = _enforce_final_score_regime(report_text, decision_state)
    score_value, _ = parse_score_regime(report_text)
    score = _safe_float(score_value)
    if score is None and isinstance(decision_state, dict):
        score = _safe_float(
            decision_state.get("final_score", decision_state.get("metric_implied_score"))
        )
    if score is None:
        score = 0.0
    policy_state = dict(decision_state or {})
    final_confidence = _extract_final_confidence(report_text)
    if final_confidence:
        policy_state["final_confidence"] = final_confidence
        if isinstance(decision_state, dict):
            decision_state["final_confidence"] = final_confidence
    policy = _allocation_policy_for_score(score, policy_state)

    heading = re.search(
        r"(?im)^#{1,4}\s*6(?:\.\d+)?\.?\s*(?:Deterministic\s+)?Executive\s+Order[^\n]*$",
        report_text,
    )
    if not heading:
        final_lines = list(
            re.finditer(
                r"(?im)^.*final\s+score\s*&\s*regime\s*[:=].*$",
                report_text,
            )
        )
        normalized = (
            "### 6. Deterministic Executive Order\n"
            "- **Cash**: **100%**\n"
            "- **Equity**: **0%**\n"
            "- **Short VN30F1M**: **0%**\n\n"
            "**Deterministic Allocation Guardrail (authoritative)**: "
            f"The Executive Order section was missing or non-canonical. {policy['label']} "
            f"permits Equity <= {policy['max_equity_pct']:.0f}% and Short VN30F1M <= "
            f"{policy['max_short_vn30f1m_pct']:.0f}%; the safe normalized order above "
            "overrides conflicting prose.\n\n"
        )
        if final_lines:
            final_line = final_lines[-1]
            return f"{report_text[:final_line.start()].rstrip()}\n\n{normalized}{report_text[final_line.start():]}"
        return f"{report_text.rstrip()}\n\n{normalized.rstrip()}\n"
    next_heading = re.search(
        r"(?im)^(?:#{1,4}\s*(?:[7-9](?:\.\d+)?\.?\s+|FINAL)|"
        r"\s*\**\s*final\s+score\s*&\s*regime\s*[:=])",
        report_text[heading.end():],
    )
    section_end = heading.end() + next_heading.start() if next_heading else len(report_text)
    section = report_text[heading.start():section_end]

    patterns = {
        "cash": re.compile(
            r"(?im)^(?P<prefix>\s*-\s*\*\*(?:Cash|Tiền\s*mặt)\*\*\s*:\s*\**\s*)"
            r"(?P<value>\d+(?:\.\d+)?)(?P<suffix>\s*%[^\n]*)$"
        ),
        "equity": re.compile(
            r"(?im)^(?P<prefix>\s*-\s*\*\*(?:Equity|Cổ\s*phiếu)\*\*\s*:\s*\**\s*)"
            r"(?P<value>\d+(?:\.\d+)?)(?P<suffix>\s*%[^\n]*)$"
        ),
        "short": re.compile(
            r"(?im)^(?P<prefix>\s*-\s*\*\*(?:Short\s+VN30F1M|Phái\s*sinh|Hedge(?:\s+instrument)?)\*\*"
            r"\s*:\s*\**\s*)(?P<value>\d+(?:\.\d+)?)(?P<suffix>\s*%[^\n]*)$"
        ),
    }

    def last_match(key: str) -> re.Match[str] | None:
        matches = list(patterns[key].finditer(section))
        return matches[-1] if matches else None

    def current_value(key: str) -> float | None:
        match = last_match(key)
        return float(match.group("value")) if match else None

    values = {key: current_value(key) for key in patterns}
    adjusted_equity = (
        min(values["equity"], policy["max_equity_pct"])
        if values["equity"] is not None
        else None
    )
    adjusted_short = (
        min(values["short"], policy["max_short_vn30f1m_pct"])
        if values["short"] is not None
        else None
    )
    adjusted_cash = 100.0 - adjusted_equity if adjusted_equity is not None else None
    targets = {
        "cash": adjusted_cash,
        "equity": adjusted_equity,
        "short": adjusted_short,
    }
    corrections: list[str] = []
    for key, target in targets.items():
        original = values[key]
        if original is None or target is None or abs(original - target) < 1e-9:
            continue
        match = last_match(key)
        if not match:
            continue
        display = f"{target:.0f}" if float(target).is_integer() else f"{target:.1f}"
        section = (
            f"{section[:match.start('value')]}{display}{section[match.end('value'):]}"
        )
        corrections.append(f"{key} {original:g}% -> {display}%")

    structured_complete = all(value is not None for value in values.values())
    prohibited_instruction = (
        not policy["bottom_fishing_allowed"]
        and re.search(
            r"(?i)(?:bottom[- ]?fish(?:ing)?|buy\s+(?:the\s+)?(?:capitulation\s+)?bottom|bắt\s+đáy|mua\s+đáy)",
            section,
        )
        is not None
    )
    if not corrections and structured_complete and not prohibited_instruction:
        return report_text

    guard_note = (
        "\n\n**Deterministic Allocation Guardrail (authoritative)**: "
        f"{policy['label']} permits Equity <= {policy['max_equity_pct']:.0f}%, "
        f"Short VN30F1M <= {policy['max_short_vn30f1m_pct']:.0f}%, and "
        f"Cash = 100% - Equity. "
    )
    if corrections:
        guard_note += "Applied corrections: " + "; ".join(corrections) + ". "
    if not structured_complete:
        normalized_equity = adjusted_equity if adjusted_equity is not None else 0.0
        normalized_short = adjusted_short if adjusted_short is not None else 0.0
        normalized_cash = 100.0 - normalized_equity
        normalized_block = (
            "\n\n**Deterministic Normalized Executive Order**\n"
            f"- **Cash**: **{normalized_cash:.0f}%**\n"
            f"- **Equity**: **{normalized_equity:.0f}%**\n"
            f"- **Short VN30F1M**: **{normalized_short:.0f}%**"
        )
        section = section.rstrip() + normalized_block
        guard_note += "Structured Cash/Equity/Short lines were incomplete; the normalized three-line order above is authoritative. "
    guard_note += "Any conflicting allocation or bottom-fishing instruction above is void."
    section = section.rstrip() + guard_note + "\n\n"
    return f"{report_text[:heading.start()]}{section}{report_text[section_end:].lstrip()}"


def _annotate_final_score_drift(report_text: str, decision_state: dict[str, Any] | None) -> str:
    """Flag large subjective overlay drift without overriding the model's final score."""
    if not decision_state:
        return report_text

    baseline_raw = decision_state.get("metric_implied_score")
    baseline_regime = _clean_regime_value(str(decision_state.get("metric_implied_regime") or ""))
    try:
        baseline = int(round(float(baseline_raw)))
    except Exception:
        return report_text
    if not baseline_regime:
        baseline_regime = regime_from_score(baseline)

    score_val, regime_val = parse_score_regime(report_text)
    try:
        final_score = int(round(float(score_val)))
    except Exception:
        return report_text
    final_regime = _clean_regime_value(str(regime_val or ""))
    score_regime = regime_from_score(final_score)
    expected_final_regime = (
        "CAPITULATION"
        if _capitulation_action_eligible(decision_state)
        else score_regime
    )
    drift = final_score - baseline
    drift_alert_points = int(decision_state.get("drift_alert_points") or 8)
    baseline_band = _score_band_for_regime(baseline_regime)
    final_in_baseline_band = baseline_band[0] <= final_score <= baseline_band[1] if baseline_band else True

    flags: list[str] = []
    if abs(drift) >= drift_alert_points:
        flags.append(f"large overlay drift {drift:+d} points versus metric_implied_score={baseline}")
    if not final_in_baseline_band:
        flags.append(f"final score moved outside metric-implied band {baseline_regime}")
    if final_regime not in ("", "N/A") and final_regime != expected_final_regime:
        flags.append(
            f"reported regime {final_regime} differs from deterministic decision regime "
            f"{expected_final_regime}"
        )
    if not flags:
        return report_text

    note = (
        "\n\n**Final Score Drift Audit**: Model final score is preserved, but review required: "
        + "; ".join(flags)
        + "."
    )
    final_pattern = re.compile(
        r"final\s+score\s*&\s*regime\s*[:=]\s*[-+]?\d+(?:\.\d+)?"
        r"\s*;\s*regime\s*[:=]\s*[^\n`]+",
        re.IGNORECASE,
    )
    matches = list(final_pattern.finditer(report_text))
    if not matches or "Final Score Drift Audit" in report_text:
        return report_text
    last = matches[-1]
    return f"{report_text[:last.start()].rstrip()}{note}\n\n{report_text[last.start():]}"


def _extract_falsification_payload(text: str) -> tuple[dict[str, Any] | None, tuple[int, int] | None]:
    marker = '"falsification_rules"'
    idx = text.find(marker)
    if idx < 0:
        return None, None

    for start in reversed([match.start() for match in re.finditer(r"\{", text[:idx])]):
        candidate = _balanced_json(text, start)
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("falsification_rules"), list):
            continue

        end = start + len(candidate)
        return payload, _expand_json_span(text, start, end)
    return None, None


def _balanced_json(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
    return None


def _expand_json_span(text: str, start: int, end: int) -> tuple[int, int]:
    marker_start = text.rfind("<!-- HUMILITY_JSON_START -->", 0, start)
    marker_end = text.find("<!-- HUMILITY_JSON_END -->", end)
    if marker_start >= 0 and marker_end >= 0:
        return marker_start, marker_end + len("<!-- HUMILITY_JSON_END -->")

    fence_start = text.rfind("```json", 0, start)
    fence_end = text.find("```", end)
    if fence_start >= 0 and fence_end >= 0:
        return fence_start, fence_end + 3
    return start, end


def _strip_incomplete_falsification_block(text: str) -> str:
    idx = text.find('"falsification_rules"')
    if idx < 0:
        return text
    marker_start = text.rfind("<!-- HUMILITY_JSON_START -->", 0, idx)
    fence_start = text.rfind("```json", 0, idx)
    brace_start = text.rfind("{", 0, idx)
    starts = [value for value in (marker_start, fence_start, brace_start) if value >= 0]
    start = min(starts) if starts else idx
    end_marker = text.find("<!-- HUMILITY_JSON_END -->", idx)
    if end_marker >= 0:
        end = end_marker + len("<!-- HUMILITY_JSON_END -->")
    else:
        fence_end = text.find("```", idx)
        end = fence_end + 3 if fence_end >= 0 else len(text)
    return text[:start].rstrip()


def _fallback_humility_payload_from_markdown(text: str) -> dict[str, Any] | None:
    score_val, regime_val = parse_score_regime(text)
    report_date = _parse_report_date_from_text(text) or date.today()
    values = _extract_humility_values_from_text(text)
    rules = []
    for key, default_rule in zip(
        ("vnibor", "breadth", "ssi", "evt", "coupling", "gfc"),
        HUMILITY_DEFAULT_RULES,
    ):
        rule = dict(default_rule)
        rule["current_value"] = values.get(key)
        rules.append(rule)

    if score_val == "N/A" and regime_val == "N/A" and not any(value is not None for value in values.values()):
        return None

    return {
        "report_date": report_date.isoformat(),
        "composite_score": None if score_val == "N/A" else float(score_val),
        "regime": None if regime_val == "N/A" else regime_val,
        "falsification_rules": rules,
        "source": "fallback_from_ai_cio_markdown",
    }


def _parse_report_date_from_text(text: str) -> date | None:
    patterns = [
        r"Ngày\s+báo\s+cáo.*?(\d{2}/\d{2}/\d{4})",
        r"Date\)\*\*\s*:\s*(\d{2}/\d{2}/\d{4})",
        r'"report_date"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if not matches:
            continue
        try:
            value = matches[-1]
            if "/" in value:
                return pd.to_datetime(value, format="%d/%m/%Y").date()
            return pd.Timestamp(value).date()
        except Exception:
            continue
    return None


def _extract_humility_values_from_text(text: str) -> dict[str, float | None]:
    patterns: dict[str, list[tuple[str, str]]] = {
        "vnibor": [
            (r"VNIBOR|STRESS", r"(\d+(?:\.\d+)?)\s*/\s*20\s*phiên\s+STRESS"),
        ],
        "breadth": [
            (r"Breadth MA20|MA20", r"từ\s+(\d+(?:\.\d+)?)%"),
            (r"Breadth MA20|MA20", r"MA20[^\n]*?(\d+(?:\.\d+)?)%"),
        ],
        "ssi": [
            (r"\bSSI\b|ESR", r"từ\s+(\d+(?:\.\d+)?)%"),
            (r"\bSSI\b|ESR", r"SSI\s+(\d+(?:\.\d+)?)%"),
        ],
        "evt": [
            (r"EVT|Tail Index|ξ|xi", r"từ\s+(\d+(?:\.\d+)?)"),
            (r"EVT|Tail Index|ξ|xi", r"(?:ξ|xi)\s*=\s*(\d+(?:\.\d+)?)"),
        ],
        "coupling": [
            (r"Coupling|Vingroup|Slope", r"từ\s+(\d+(?:\.\d+)?)th"),
        ],
        "gfc": [
            (r"Global Financial Conditions|CQS", r"từ\s+(\d+(?:\.\d+)?)th"),
            (r"Global Financial Conditions|CQS", r"CQS\s+(\d+(?:\.\d+)?)th"),
        ],
    }
    values: dict[str, float | None] = {key: None for key in patterns}
    for line in text.splitlines():
        for key, cases in patterns.items():
            if values[key] is not None:
                continue
            for line_pattern, value_pattern in cases:
                if not re.search(line_pattern, line, flags=re.IGNORECASE):
                    continue
                match = re.search(value_pattern, line, flags=re.IGNORECASE)
                if match:
                    values[key] = float(match.group(1))
                    break
    return values


def _write_humility_rules_payload(payload: dict[str, Any], provider_key: str) -> Path:
    report_date = _payload_date(payload.get("report_date")) or date.today()
    sidecar_path = _get_humility_rules_path(provider_key, report_date)
    normalized = dict(payload)
    normalized["report_date"] = report_date.isoformat()
    normalized["provider_key"] = provider_key
    normalized["saved_at"] = date.today().isoformat()
    normalized["source"] = "ai_cio_executive_summary"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar_path


def _payload_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _payload_number_as_text(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if pd.isna(number):
        return "N/A"
    return str(int(number)) if number.is_integer() else str(number)


def _has_final_score_line(text: str) -> bool:
    return bool(
        re.search(
            r"final\s+score\s*&\s*regime\s*[:=]\s*[-+]?\d+(?:\.\d+)?\s*;\s*regime\s*[:=]",
            text,
            flags=re.IGNORECASE,
        )
    )


def _clean_context_line(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("**", "").replace("`", "")


def _compact_text(text: str, max_chars: int = 1400) -> str:
    """Keep a bounded evidence excerpt instead of feeding raw reports forward."""
    if not text:
        return ""
    lines = [_clean_context_line(line) for line in str(text).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    priority_terms = (
        "score", "regime", "risk", "tail", "ssi", "var", "cvar", "evt", "xi",
        "breadth", "vnibor", "liquidity", "stress", "allocation", "cash",
        "equity", "hedge", "falsification", "watch", "falsified", "confidence",
        "macro", "market", "alpha", "valuation", "cqs", "pc1", "ltmm",
        "fli", "mli", "fri", "transmission", "bottleneck", "trigger",
        "overlay", "credit spread", "risk premium", "bank yield", "real estate yield",
    )
    selected: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(term in lower for term in priority_terms):
            selected.append(line)
        if len(selected) >= 10:
            break
    if len(selected) < 4:
        selected.extend(line for line in lines[:8] if line not in selected)

    compact = "\n".join(f"- {line}" for line in selected)
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 80].rstrip() + "\n- [trimmed: raw report omitted]"


def _infer_evidence_bias(text: str) -> str:
    lower = str(text or "").lower()
    bearish_terms = (
        "bearish", "risk-off", "stress", "critical", "crisis", "panic",
        "distribution", "pre-crash", "elevated", "extreme", "warning",
        "headwind", "tightening", "cash 100", "avoid",
    )
    bullish_terms = (
        "bullish", "risk-on", "uptrend", "expansion", "calm", "manageable",
        "recovery", "easing", "tailwind", "improving", "undervalued",
        "positive", "accumulation",
    )
    bearish = sum(lower.count(term) for term in bearish_terms)
    bullish = sum(lower.count(term) for term in bullish_terms)
    if bearish >= bullish + 2:
        return "bearish"
    if bullish >= bearish + 2:
        return "bullish"
    return "neutral_or_mixed"


def _is_scoring_evidence_packet(packet: dict[str, Any]) -> bool:
    """Keep audit/diagnostic evidence out of deterministic live scoring."""
    if (
        packet.get("layer") in {"history", "audit"}
        or str(packet.get("tool") or "") in NON_SCORING_EVIDENCE_TOOLS
    ):
        return False
    explicit = packet.get("scoring_eligible")
    if isinstance(explicit, bool):
        return explicit
    return True


def _format_evt_xi_summary(snap: dict[str, Any], xi_label: str) -> str:
    xi_text = f"{snap['evt_xi']:+.3f} MLE ({xi_label})"
    if snap.get("evt_interval_available"):
        xi_text += (
            f"; MCMC posterior p50 {snap['evt_xi_p50']:+.3f}, "
            f"90% CI [{snap['evt_xi_p05']:+.3f}, {snap['evt_xi_p95']:+.3f}]"
        )
    return xi_text


def _build_evidence_packet(
    tool_id: str,
    report_text: str,
    layer: str,
    date_label: str | None = None,
    max_excerpt_chars: int = 1400,
    direct_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a verbose child report into a bounded evidence packet for AI CIO."""
    text = str(report_text or "").strip()
    score_val, regime_val = parse_score_regime(text)
    packet: dict[str, Any] = {
        "tool": tool_id,
        "layer": layer,
        "date": date_label or "N/A",
        "scoring_eligible": (
            layer not in {"history", "audit"}
            and tool_id not in NON_SCORING_EVIDENCE_TOOLS
        ),
        "bias": _infer_evidence_bias(text),
        "score": None if score_val == "N/A" else score_val,
        "regime": None if regime_val == "N/A" else regime_val,
        "key_metrics": {},
        "metric_provenance": {},
        "metric_consistency": {
            "status": "NOT_SCORING",
            "warnings": [],
            "blocked_candidates": [],
        },
        "evidence_excerpt": _compact_text(text, max_chars=max_excerpt_chars),
    }

    # Audit packets quote prior thresholds alongside current observations. Generic
    # metric regexes cannot distinguish those roles, so retain the bounded evidence
    # but never promote its numbers into the live metric contract.
    if not _is_scoring_evidence_packet(packet):
        return packet

    resolution = resolve_tool_metrics(
        tool_id,
        text,
        direct_metrics=direct_metrics,
    )
    packet["key_metrics"] = resolution.metrics
    packet["metric_provenance"] = resolution.provenance
    packet["metric_consistency"] = resolution.consistency
    adapter_score = score_tool_packet(tool_id, packet["key_metrics"])
    if adapter_score:
        packet["adapter_score"] = adapter_score
        packet["bias"] = adapter_score["tool_bias"]
    return packet


def _format_json_context(title: str, payload: Any) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return f"=== {title} ===\n```json\n{body}\n```"


def _append_structured_footer(report_text: str, title: str, lines: list[str]) -> str:
    clean_lines = [str(line).strip() for line in lines if str(line).strip()]
    if not clean_lines:
        return str(report_text or "")
    return (
        str(report_text or "").rstrip()
        + f"\n\n=== AI CIO STRUCTURED METRICS: {title} ===\n"
        + "\n".join(f"- {line}" for line in clean_lines)
        + "\n"
    )


def build_pvgo_ai_cio_metric_context(coe_pct: float = 14.0) -> str:
    """Return PVGO prose plus the authoritative code-generated metric contract."""

    context = build_pvgo_ai_cio_context(coe_pct=coe_pct)
    try:
        snap = pvgo_snapshot(coe_pct=coe_pct)
    except Exception:
        return context
    if snap.get("status") != "OK":
        return context
    freshness = snap.get("freshness") if isinstance(snap.get("freshness"), dict) else {}
    if freshness.get("status") == "STALE":
        return context
    return _append_direct_metrics(
        context,
        "pvgo",
        {
            "pvgo_pct": snap.get("pvgo_pct"),
            "pe": snap.get("pe"),
            "pb": snap.get("pb"),
            "coe_pct": snap.get("coe_pct"),
            "pvgo_zscore": snap.get("pvgo_zscore"),
            "pvgo_status": snap.get("pvgo_status"),
            "freshness_status": freshness.get("status"),
            "freshness_session_lag": freshness.get("session_lag"),
        },
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return None
        return float(value)
    except Exception:
        return None


def _packet_metrics(evidence_packets: list[dict[str, Any]], tool_id: str) -> dict[str, Any]:
    for packet in evidence_packets:
        if str(packet.get("tool") or "") == tool_id:
            metrics = packet.get("key_metrics")
            return dict(metrics) if isinstance(metrics, dict) else {}
    return {}


def _packet_metrics_as_of(
    evidence_packets: list[dict[str, Any]],
    tool_id: str,
    market_index: pd.Index,
    expected_as_of: pd.Timestamp,
    max_session_lag: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = next(
        (
            item
            for item in evidence_packets
            if str(item.get("tool") or "") == tool_id
        ),
        None,
    )
    raw_date = str((packet or {}).get("date") or "")
    parsed_date = _parse_ledger_date({"date": raw_date})
    metadata: dict[str, Any] = {
        "packet_date": raw_date or None,
        "session_lag": None,
        "status": "MISSING",
        "used": False,
    }
    if packet is None or parsed_date is None:
        metadata["status"] = "MISSING" if packet is None else "INVALID_DATE"
        return {}, metadata

    packet_stamp = pd.Timestamp(parsed_date)
    expected = pd.Timestamp(expected_as_of).normalize()
    if packet_stamp.normalize() > expected:
        metadata["status"] = "FUTURE_MISMATCH"
        return {}, metadata

    sessions = pd.DatetimeIndex(pd.to_datetime(market_index)).normalize().unique().sort_values()
    sessions = sessions[sessions <= expected]
    packet_sessions = sessions[sessions <= packet_stamp.normalize()]
    if packet_sessions.empty:
        metadata["status"] = "OUT_OF_SAMPLE"
        return {}, metadata
    packet_session = packet_sessions[-1]
    session_lag = int(((sessions > packet_session) & (sessions <= expected)).sum())
    metadata["session_lag"] = session_lag
    if session_lag > max_session_lag:
        metadata["status"] = "STALE"
        return {}, metadata

    metadata["status"] = "CURRENT" if session_lag == 0 else "PREVIOUS_SESSION"
    metadata["used"] = True
    return _packet_metrics(evidence_packets, tool_id), metadata


def _load_abm_metric_history_as_of(
    as_of: Any,
    data_lake: Path | None = None,
) -> pd.DataFrame:
    """Load explicitly dated ABM state available on or before ``as_of``."""

    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    cutoff = cutoff.normalize()
    base_dir = Path(data_lake) if data_lake is not None else DATA_LAKE
    frames: list[pd.DataFrame] = []
    metric_names = {
        "vulnerability",
        "vulnerability_score",
        "system_vulnerability",
        "cascade_vulnerability",
        "margin_distance",
        "margin_distance_pct",
        "distance_to_margin_call",
        "distance_to_margin_call_pct",
        "distance_to_cascade",
        "distance_to_cascade_pct",
        "forced_selling_share",
        "forced_liquidation_share",
        "liquidation_share",
        "panic_share",
        "panic_rate",
        "panic_probability",
        "panic_pct",
        "panic_ratio_pct",
        "orange_share",
        "orange_pct",
        "orange",
        "red_share",
        "red_pct",
        "red",
    }

    for filename in ("abm_behavioral_state.csv", "abm_alert.csv"):
        path = base_dir / filename
        if not path.exists():
            continue
        try:
            raw = pd.read_csv(path)
        except (OSError, UnicodeError, pd.errors.ParserError):
            continue
        if raw.empty:
            continue

        normalized_columns = {
            str(column).strip().lower(): column for column in raw.columns
        }
        date_column = next(
            (
                normalized_columns[name]
                for name in ("as_of_date", "as_of", "date", "timestamp")
                if name in normalized_columns
            ),
            None,
        )
        if date_column is None:
            continue
        metric_columns = [
            column
            for normalized, column in normalized_columns.items()
            if normalized in metric_names
        ]
        if not metric_columns:
            continue

        parsed_dates = pd.to_datetime(
            raw[date_column],
            errors="coerce",
            format="mixed",
            dayfirst=True,
        )
        if getattr(parsed_dates.dt, "tz", None) is not None:
            parsed_dates = parsed_dates.dt.tz_localize(None)
        parsed_dates = parsed_dates.dt.normalize()
        frame = raw.loc[:, metric_columns].apply(pd.to_numeric, errors="coerce")
        frame.index = pd.DatetimeIndex(parsed_dates, name="as_of_date")
        frame = frame.loc[frame.index.notna() & (frame.index <= cutoff)]
        frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="as_of_date"))

    history = pd.concat(frames, axis=1).sort_index()
    history = history.loc[:, ~history.columns.duplicated(keep="last")]
    return history.loc[history.index <= cutoff]


def _merge_abm_history_with_current_metrics(
    history: pd.DataFrame,
    current_metrics: dict[str, Any],
    market_index: pd.Index,
    as_of: Any,
) -> pd.DataFrame:
    """Expose dated history while keeping the live ABM view freshness-bounded."""

    stamp = pd.Timestamp(as_of)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    stamp = stamp.normalize()
    frame = history.copy()
    if not frame.empty:
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).tz_localize(None).normalize()
        frame = frame.loc[frame.index <= stamp]

    sessions = pd.DatetimeIndex(pd.to_datetime(market_index)).tz_localize(None).normalize()
    sessions = sessions[(sessions <= stamp)].unique().sort_values()
    if not frame.empty:
        union = frame.index.union(sessions).union(pd.DatetimeIndex([stamp])).sort_values()
        current_row = frame.reindex(union).ffill(limit=1).reindex([stamp]).iloc[0]
    else:
        current_row = pd.Series(dtype=object)

    for key, value in (current_metrics or {}).items():
        current_row[str(key)] = value

    if frame.empty and current_row.empty:
        return frame

    live_row = current_row.to_frame().T
    live_row.index = pd.DatetimeIndex([stamp], name="as_of_date")
    frame = pd.concat([frame.loc[frame.index != stamp], live_row], axis=0, sort=False)
    return frame.loc[~frame.index.duplicated(keep="last")].sort_index()


def _insufficient_capitulation_state(reason: str, expected_as_of: Any = None) -> dict[str, Any]:
    expected = pd.Timestamp(expected_as_of).isoformat() if expected_as_of is not None else None
    return {
        "as_of": None,
        "expected_as_of": expected,
        "freshness_status": "UNAVAILABLE",
        "phase": "DATA_INSUFFICIENT",
        "stress_risk_score_uncalibrated": None,
        "liquidation_risk_score_uncalibrated": None,
        "exhaustion_evidence_score_uncalibrated": None,
        "features": {},
        "percentiles": {},
        "required_gates_met": {
            "price_shock": False,
            "breadth_shock": False,
            "forced_selling": False,
            "three_gate_climax": False,
            "post_climax_exhaustion": False,
        },
        "trigger_reasons": ("Capitulation detector unavailable",),
        "confirmation_reasons": (),
        "data_quality": {
            "status": "INSUFFICIENT",
            "warnings": (str(reason)[:400],),
        },
        "action_eligible": False,
        "methodology_version": CAPITULATION_METHODOLOGY_VERSION,
        "score_interpretation": (
            "Deterministic 0-100 evidence scores; uncalibrated and not probabilities."
        ),
    }


def _build_capitulation_state(
    df_stocks: pd.DataFrame,
    evidence_packets: list[dict[str, Any]],
    report_as_of: Any = None,
) -> dict[str, Any]:
    """Run the point-in-time phase detector without feeding it back into the score."""

    expected_as_of = pd.Timestamp(df_stocks.index[-1]) if not df_stocks.empty else None
    report_timestamp = pd.Timestamp(
        report_as_of if report_as_of is not None else date.today()
    ).normalize()
    try:
        if expected_as_of is None:
            raise ValueError("constituent market data are empty")
        esr_metrics, esr_freshness = _packet_metrics_as_of(
            evidence_packets,
            "esr_monitor",
            df_stocks.index,
            expected_as_of,
        )
        abm_metrics, abm_freshness = _packet_metrics_as_of(
            evidence_packets,
            "abm_simulator",
            df_stocks.index,
            expected_as_of,
        )
        abm_history = _load_abm_metric_history_as_of(expected_as_of)
        dated_abm_metrics = _merge_abm_history_with_current_metrics(
            abm_history,
            abm_metrics,
            df_stocks.index,
            expected_as_of,
        )
        index_frame = load_custom("vnindex_cache.csv")
        normalized_columns = {str(column).strip().lower(): column for column in index_frame.columns}
        close_column = normalized_columns.get("vnindex")
        if close_column is None:
            raise ValueError("vnindex_cache.csv has no VNINDEX close column")
        volume_column = normalized_columns.get("vnindex_volume")
        constituent_volume = load_volumes()
        snapshot = analyze_capitulation(
            index_close=index_frame[close_column],
            constituent_close=df_stocks,
            index_volume=index_frame[volume_column] if volume_column is not None else None,
            constituent_volume=constituent_volume,
            esr_metrics=esr_metrics,
            abm_metrics=dated_abm_metrics,
            as_of=expected_as_of,
        )
    except Exception as exc:
        return _insufficient_capitulation_state(
            f"{type(exc).__name__}: {exc}",
            expected_as_of=expected_as_of,
        )

    state = snapshot.to_dict()
    state["external_metric_freshness"] = {
        "esr_monitor": esr_freshness,
        "abm_simulator": abm_freshness,
    }
    state["expected_as_of"] = expected_as_of.isoformat() if expected_as_of is not None else None
    state["report_as_of"] = report_timestamp.isoformat()
    actual_as_of = pd.Timestamp(snapshot.as_of)
    market_timestamp = expected_as_of.normalize()
    if report_timestamp >= market_timestamp:
        market_data_lag = len(
            pd.bdate_range(market_timestamp + pd.offsets.BDay(1), report_timestamp)
        )
    else:
        market_data_lag = -len(
            pd.bdate_range(report_timestamp + pd.offsets.BDay(1), market_timestamp)
        )
    state["market_data_lag_business_days"] = market_data_lag
    state["market_data_freshness_policy"] = "current or previous business session"
    detector_matches_market = actual_as_of.normalize() == market_timestamp
    is_current = detector_matches_market and 0 <= market_data_lag <= 1
    state["freshness_status"] = "CURRENT" if is_current else "STALE"
    if not is_current:
        state["action_eligible"] = False
        quality = state.get("data_quality") if isinstance(state.get("data_quality"), dict) else {}
        warnings = list(quality.get("warnings") or [])
        if not detector_matches_market:
            warnings.append(
                f"detector as_of {actual_as_of.date()} differs from market data {expected_as_of.date()}"
            )
        if market_data_lag < 0:
            warnings.append(
                f"market data {expected_as_of.date()} are future-dated versus report {report_timestamp.date()}"
            )
        elif market_data_lag > 1:
            warnings.append(
                f"market data lag is {market_data_lag} business days versus report date; action gate disabled"
            )
        quality["warnings"] = warnings
        if quality.get("status") == "GOOD":
            quality["status"] = "LIMITED"
        state["data_quality"] = quality
    stale_external = [
        tool
        for tool, metadata in state["external_metric_freshness"].items()
        if metadata.get("used") is not True
    ]
    if stale_external:
        quality = state.get("data_quality") if isinstance(state.get("data_quality"), dict) else {}
        warnings = list(quality.get("warnings") or [])
        warnings.append(
            "external detector metrics excluded by as-of policy: " + ", ".join(stale_external)
        )
        quality["warnings"] = warnings
        if quality.get("status") == "GOOD":
            quality["status"] = "LIMITED"
        state["data_quality"] = quality
    return state


def _build_capitulation_evidence_packet(state: dict[str, Any]) -> dict[str, Any]:
    phase = str(state.get("phase") or "DATA_INSUFFICIENT")
    features = state.get("features") if isinstance(state.get("features"), dict) else {}
    diagnostic = {
        "phase": phase,
        "stress_risk_score_uncalibrated": state.get("stress_risk_score_uncalibrated"),
        "liquidation_risk_score_uncalibrated": state.get("liquidation_risk_score_uncalibrated"),
        "exhaustion_evidence_score_uncalibrated": state.get(
            "exhaustion_evidence_score_uncalibrated"
        ),
        "required_gates_met": state.get("required_gates_met"),
        "action_eligible": state.get("action_eligible") is True,
        "freshness_status": state.get("freshness_status"),
        "market_data_lag_business_days": state.get("market_data_lag_business_days"),
        "external_metric_freshness": state.get("external_metric_freshness"),
        "data_quality": state.get("data_quality"),
        "price_structure": {
            key: features.get(key)
            for key in (
                "return_1d",
                "return_5d",
                "drawdown",
                "ma200_gap",
                "downside_participation",
                "new_low_252",
                "breadth_ma20",
                "turnover_ratio_20",
            )
        },
        "trigger_reasons": state.get("trigger_reasons"),
        "confirmation_reasons": state.get("confirmation_reasons"),
    }
    return {
        "tool": "capitulation_regime",
        "layer": "regime_gate",
        "date": state.get("as_of") or "N/A",
        "scoring_eligible": False,
        "consensus_eligible": False,
        "diagnostic_metrics_visible": True,
        "bias": "neutral_or_mixed",
        "score": None,
        "regime": phase,
        "key_metrics": diagnostic,
        "evidence_excerpt": _compact_text(
            json.dumps(diagnostic, ensure_ascii=False, default=str),
            max_chars=2200,
        ),
    }


def _attach_capitulation_policy(
    decision_state: dict[str, Any],
    capitulation_state: dict[str, Any],
) -> dict[str, Any]:
    """Attach the gate and resolve the baseline decision regime fail-closed."""

    phase = str(capitulation_state.get("phase") or "DATA_INSUFFICIENT").upper()
    action_eligible = _capitulation_action_eligible(
        {"capitulation_state": capitulation_state}
    )
    stress_regime = str(decision_state.get("metric_implied_regime") or "")
    resolved_regime = "CAPITULATION" if action_eligible else stress_regime
    decision_state["score_semantics"] = (
        "Monotonic health/stress score; lower is worse and does not identify a bottom."
    )
    decision_state["baseline_stress_regime"] = stress_regime
    decision_state["baseline_resolved_regime"] = resolved_regime
    # Legacy aliases remain the pre-LLM values until final post-processing.
    decision_state["stress_regime"] = stress_regime
    decision_state["capitulation_state"] = capitulation_state
    decision_state["capitulation_override_active"] = action_eligible
    decision_state["resolved_regime"] = resolved_regime
    score = _safe_float(decision_state.get("metric_implied_score"))
    decision_state["allocation_guardrail"] = (
        _allocation_policy_for_score(score, decision_state) if score is not None else None
    )

    constraints = list(decision_state.get("hard_constraints") or [])
    if phase in {"LIQUIDATION", "CAPITULATION_CLIMAX"}:
        constraints.append(
            f"Bottom-fishing prohibited: capitulation phase is {phase}; exhaustion is not confirmed"
        )
    elif phase == "FRAGILE":
        constraints.append("Capitulation gate is FRAGILE; no bottom or short-closing override")
    elif phase == "EXHAUSTION_CONFIRMED" and action_eligible:
        constraints.append(
            "CAPITULATION override active: exhaustion confirmed with usable data; close shorts and use tranche-only equity"
        )
    elif phase in {"EXHAUSTION_CONFIRMED", "DATA_INSUFFICIENT"}:
        constraints.append(
            "Capitulation override prohibited: confirmation data are insufficient, stale, or not action-eligible"
        )
    decision_state["hard_constraints"] = sorted(set(constraints))

    writer_rules = list(decision_state.get("writer_rules") or [])
    writer_rules.extend(
        [
            "Do not interpret capitulation evidence scores as probabilities.",
            "Do not add the capitulation gate to the composite score or consensus; it reuses price, breadth, ESR, and ABM evidence.",
            "Use CAPITULATION only when capitulation_state.phase is EXHAUSTION_CONFIRMED and action_eligible is true.",
            "LIQUIDATION and CAPITULATION_CLIMAX prohibit bottom-fishing; they are not reversal confirmations.",
        ]
    )
    decision_state["writer_rules"] = list(dict.fromkeys(writer_rules))
    return decision_state


def _round_or_none(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _parse_ledger_date(row: dict[str, Any]) -> date | None:
    raw = str(row.get("date") or row.get("ddmmyyyy") or "")
    for fmt in ("%Y-%m-%d", "%d%m%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


def _history_row_sort_key(row: dict[str, Any]) -> str:
    parsed = _parse_ledger_date(row)
    return parsed.isoformat() if parsed else str(row.get("date") or "")


def _build_history_rollup(
    history_ledger: list[dict[str, Any]],
    current_score: Any = None,
    current_regime: str | None = None,
    current_date_label: str | None = None,
) -> dict[str, Any]:
    """Build compact deterministic history stats for AI CIO; no LLM trend summarizer needed."""

    def optional_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        return None

    rows = sorted(history_ledger or [], key=_history_row_sort_key)
    compact_history: list[dict[str, Any]] = []
    for row in rows[-AI_CIO_HISTORY_WINDOW:]:
        score = _safe_float(row.get("score"))
        compact_row = {
            "date": row.get("date"),
            "score": None if score is None else int(round(score)),
            "regime": row.get("regime", "N/A"),
            "source": row.get("source", ""),
            "provider": row.get("provider", ""),
        }
        for key in ("stress_regime", "capitulation_phase"):
            value = row.get(key)
            if value not in (None, ""):
                compact_row[key] = value
        action_eligible = optional_bool(row.get("capitulation_action_eligible"))
        if action_eligible is not None:
            compact_row["capitulation_action_eligible"] = action_eligible
        compact_history.append(compact_row)

    series = list(compact_history)
    current_numeric = _safe_float(current_score)
    if current_numeric is not None:
        series.append(
            {
                "date": current_date_label or date.today().isoformat(),
                "score": int(round(current_numeric)),
                "regime": current_regime or regime_from_score(current_numeric),
                "source": "current_metric_implied",
                "provider": "deterministic_adapter",
            }
        )

    scores = [float(item["score"]) for item in series if item.get("score") is not None]
    previous_score = None
    if current_numeric is not None and compact_history:
        previous_score = compact_history[-1].get("score")
    elif len(scores) >= 2:
        previous_score = scores[-2]

    def score_change(back: int) -> float | None:
        if not scores:
            return None
        reference_index = len(scores) - 1 - back
        if reference_index < 0:
            return None
        return scores[-1] - scores[reference_index]

    def consecutive_below(threshold: float) -> int:
        count = 0
        for item in reversed(series):
            score = _safe_float(item.get("score"))
            if score is None or score >= threshold:
                break
            count += 1
        return count

    regime_streak = 0
    current_regime_value = str(series[-1].get("regime") or "") if series else ""
    for item in reversed(series):
        if str(item.get("regime") or "") != current_regime_value:
            break
        regime_streak += 1

    scores_20 = scores[-20:]
    rolling_summary = {
        "history_count": len(compact_history),
        "current_baseline_score": None if current_numeric is None else int(round(current_numeric)),
        "current_baseline_regime": current_regime or (regime_from_score(current_numeric) if current_numeric is not None else None),
        "latest_prior_score": previous_score,
        "score_avg_5d": _round_or_none(_average(scores[-5:])),
        "score_avg_10d": _round_or_none(_average(scores[-10:])),
        "score_avg_20d": _round_or_none(_average(scores_20)),
        "score_change_1d": _round_or_none(score_change(1)),
        "score_change_5d": _round_or_none(score_change(5)),
        "score_change_10d": _round_or_none(score_change(10)),
        "days_below_30": consecutive_below(30),
        "days_below_15": consecutive_below(15),
        "current_regime_streak": regime_streak,
        "min_20d": None if not scores_20 else int(round(min(scores_20))),
        "max_20d": None if not scores_20 else int(round(max(scores_20))),
        "usage_rule": "Use for persistence/delta only. Do not anchor the final score to history.",
    }
    return {
        "window_size": AI_CIO_HISTORY_WINDOW,
        "history_window": compact_history,
        "rolling_summary": rolling_summary,
    }


def _methodology_card_for_tool(tool_id: str) -> dict[str, Any]:
    tool = str(tool_id or "")
    card = TOOL_METHODOLOGY_CARDS.get(tool)
    if card is None:
        card = {
            "domain": "unspecified",
            "horizon": "unspecified",
            "primary_metric": "see_tool_packet",
            "score_direction": "Use adapter score if present.",
            "limits": "If structured metrics are missing, mark DATA INSUFFICIENT.",
            "authority": "Adapter score/regime/bias are authoritative when available.",
        }
    return {"tool": tool, **card}


def _build_methodology_cards(evidence_packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cards: list[dict[str, Any]] = []
    for packet in evidence_packets:
        tool = str(packet.get("tool") or "")
        if not tool or tool in seen or packet.get("layer") == "history":
            continue
        seen.add(tool)
        cards.append(_methodology_card_for_tool(tool))
    return cards


def _build_tool_metrics_snapshot(evidence_packets: list[dict[str, Any]]) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for packet in evidence_packets:
        if packet.get("layer") == "history":
            continue
        tool = str(packet.get("tool") or "")
        if not tool:
            continue
        scoring_eligible = _is_scoring_evidence_packet(packet)
        diagnostic_visible = packet.get("diagnostic_metrics_visible") is True
        metrics = (packet.get("key_metrics") or {}) if scoring_eligible or diagnostic_visible else {}
        metric_provenance = (
            packet.get("metric_provenance") or {}
            if scoring_eligible or diagnostic_visible
            else {}
        )
        metric_consistency = (
            packet.get("metric_consistency") or {}
            if scoring_eligible or diagnostic_visible
            else {}
        )
        adapter_score = packet.get("adapter_score") if scoring_eligible else None
        if scoring_eligible and not isinstance(adapter_score, dict):
            adapter_score = score_tool_packet(tool, metrics)
        tools[tool] = {
            "tool": tool,
            "layer": packet.get("layer"),
            "as_of": packet.get("date"),
            "bias": packet.get("bias"),
            "report_score": packet.get("score"),
            "report_regime": packet.get("regime"),
            "key_metrics": metrics,
            "scoring_eligible": scoring_eligible,
            "diagnostic_gate_only": diagnostic_visible and not scoring_eligible,
            "adapter_available": isinstance(adapter_score, dict),
            "tool_score": adapter_score.get("tool_score") if isinstance(adapter_score, dict) else None,
            "tool_regime": adapter_score.get("tool_regime") if isinstance(adapter_score, dict) else None,
            "tool_bias": adapter_score.get("tool_bias") if isinstance(adapter_score, dict) else None,
            "score_reason": adapter_score.get("score_reason") if isinstance(adapter_score, dict) else None,
            "metric_provenance": metric_provenance,
            "metric_consistency": metric_consistency,
            "metric_authority": (
                "direct_quantitative"
                if "direct_quantitative" in set(metric_provenance.values())
                else "structured_tail_json"
                if "structured_tail_json" in set(metric_provenance.values())
                else "prose_regex_fallback"
                if "prose_regex_fallback" in set(metric_provenance.values())
                else None
            ),
            "data_quality": (
                "deterministic_gate_only"
                if diagnostic_visible and not scoring_eligible
                else "audit_evidence_only"
                if not scoring_eligible
                else "direct_quantitative"
                if "direct_quantitative" in set(metric_provenance.values())
                else "structured_tail_json"
                if "structured_tail_json" in set(metric_provenance.values())
                else "prose_regex_fallback"
                if "prose_regex_fallback" in set(metric_provenance.values())
                else "structured_adapter"
                if isinstance(adapter_score, dict)
                else "soft_excerpt_only"
            ),
        }
    return tools


def _build_ai_cio_metrics_snapshot(
    provider_key: str,
    report_date: str,
    data_date: str,
    decision_state: dict[str, Any],
    evidence_packets: list[dict[str, Any]],
    history_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    """Single deterministic metrics payload used by AI CIO and persisted for audit."""

    history = _build_history_rollup(
        history_ledger=history_ledger,
        current_score=decision_state.get("metric_implied_score"),
        current_regime=(
            decision_state.get("resolved_regime")
            or decision_state.get("metric_implied_regime")
        ),
        current_date_label=date.today().isoformat(),
    )
    methodology_cards = _build_methodology_cards(evidence_packets)
    return {
        "metrics_version": AI_CIO_METRICS_VERSION,
        "provider": provider_key,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_date": report_date,
        "data_date": data_date,
        "authority_rules": [
            "This JSON is deterministic and generated by code before final LLM synthesis.",
            "Metric authority is direct_quantitative > structured_tail_json > prose_regex_fallback; lower-priority mismatches are blocked and audited.",
            "Adapter tool_score/tool_regime/tool_bias are authoritative when present.",
            "Packets with scoring_eligible=false cannot affect composite metric inputs, bias counts, or tool-score consensus; a deterministic gate may add explicit phase-policy constraints.",
            "The capitulation_regime packet is a deterministic gate: it can resolve the decision regime but cannot enter the composite score or consensus.",
            "LLM may explain or lightly overlay, but must not relabel adapter outputs from prose.",
            "History is for persistence/delta only; it must not anchor today's final score.",
            "Human report excerpts are supporting evidence, not the scoring source of truth.",
        ],
        "score_anchor": {
            "metric_implied_score": decision_state.get("metric_implied_score"),
            "metric_implied_regime": decision_state.get("metric_implied_regime"),
            "baseline_stress_regime": decision_state.get("baseline_stress_regime"),
            "baseline_resolved_regime": decision_state.get("baseline_resolved_regime"),
            "stress_regime": decision_state.get("stress_regime"),
            "resolved_regime": decision_state.get("resolved_regime"),
            "capitulation_override_active": decision_state.get("capitulation_override_active"),
            "capitulation_state": decision_state.get("capitulation_state"),
            "allocation_guardrail": decision_state.get("allocation_guardrail"),
            "metric_implied_subscores": decision_state.get("metric_implied_subscores"),
            "score_band_reason": decision_state.get("score_band_reason"),
            "hard_constraints": decision_state.get("hard_constraints"),
        },
        "consensus": decision_state.get("consensus_map"),
        "tools": _build_tool_metrics_snapshot(evidence_packets),
        "history": history,
        "methodology_cards": methodology_cards,
    }


def _get_ai_cio_metrics_snapshot_path(
    target_date: date | None = None,
    provider_key: str | None = None,
) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    provider = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(provider_key or "").strip())
    filename = f"metrics_{provider}_{date_key}.json" if provider else f"metrics_{date_key}.json"
    return DATA_LAKE / AI_CIO_METRICS_DIRNAME / filename


def _provider_metrics_files(data_lake: Path, provider_key: str) -> list[Path]:
    """Return only persisted metric snapshots owned by the selected provider."""

    metrics_dir = Path(data_lake) / AI_CIO_METRICS_DIRNAME
    selected: list[Path] = []
    for path in metrics_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(payload.get("provider") or "") == str(provider_key):
            selected.append(path)
    return sorted(selected)


def _write_ai_cio_metrics_snapshot(snapshot: dict[str, Any], target_date: date | None = None) -> Path:
    provider_key = str(snapshot.get("provider") or "").strip()
    path = _get_ai_cio_metrics_snapshot_path(target_date, provider_key or None)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    path.write_text(payload, encoding="utf-8")
    # Keep legacy aliases for existing readers while provider-aware readers use
    # the collision-free files above.
    legacy_dated_path = _get_ai_cio_metrics_snapshot_path(target_date)
    if legacy_dated_path != path:
        legacy_dated_path.write_text(payload, encoding="utf-8")
    latest_path = path.parent / "latest.json"
    latest_path.write_text(payload, encoding="utf-8")
    if provider_key:
        safe_provider = re.sub(r"[^a-zA-Z0-9_.-]+", "-", provider_key)
        (path.parent / f"latest_{safe_provider}.json").write_text(payload, encoding="utf-8")
    return path


def _compact_metrics_snapshot_for_prompt(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics_version": snapshot.get("metrics_version"),
        "report_date": snapshot.get("report_date"),
        "data_date": snapshot.get("data_date"),
        "authority_rules": snapshot.get("authority_rules"),
        "score_anchor": snapshot.get("score_anchor"),
        "consensus": snapshot.get("consensus"),
        "tools": snapshot.get("tools"),
        "history": snapshot.get("history"),
    }


def _read_recent_summary_ledger(provider_key: str = "kimi-2.6", n_past: int = AI_CIO_HISTORY_WINDOW) -> list[dict[str, Any]]:
    """Read compact history from CSV/cache instead of injecting raw old reports."""
    rows: list[dict[str, Any]] = []
    if CSV_HISTORY_PATH.exists():
        try:
            with CSV_HISTORY_PATH.open("r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    raw_date = row.get("ddmmyyyy", "")
                    try:
                        row_date = datetime.strptime(raw_date, "%d%m%Y").date()
                    except Exception:
                        continue
                    if row_date >= date.today():
                        continue
                    item = {
                        "date": row_date.isoformat(),
                        "score": row.get("score", "N/A"),
                        "regime": row.get("regime", "N/A"),
                        "source": row.get("source", ""),
                        "provider": row.get("provider", ""),
                    }
                    optional_fields = {
                        "stress_regime": row.get("stress_regime", ""),
                        "capitulation_phase": row.get("capitulation_phase", ""),
                        "capitulation_action_eligible": row.get(
                            "capitulation_action_eligible", ""
                        ),
                    }
                    item.update(
                        {key: value for key, value in optional_fields.items() if value not in (None, "")}
                    )
                    rows.append(item)
        except Exception:
            rows = []

    rows = sorted(rows, key=lambda item: item["date"], reverse=True)
    provider_rows = [row for row in rows if row.get("provider") in ("", provider_key)]
    selected = (provider_rows or rows)[:n_past]
    if len(selected) >= n_past:
        return selected

    seen_dates = {row["date"] for row in selected}
    cache_dir = DATA_LAKE / "daily_cache"
    for days_back in range(1, max(31, n_past * 2) + 1):
        if len(selected) >= n_past:
            break
        target_date = date.today() - timedelta(days=days_back)
        if target_date.isoformat() in seen_dates:
            continue
        date_str = target_date.strftime('%d%m%y')
        path = cache_dir / f"executive_summary_{provider_key}_{date_str}.txt"
        if not path.exists():
            alt_paths = list(cache_dir.glob(f"executive_summary_*_{date_str}.txt"))
            if alt_paths:
                path = alt_paths[0]
        if path.exists():
            content = strip_wrapping_markdown_fence(path.read_text(encoding="utf-8").strip())
            score_val, regime_val = parse_score_regime(content)
            selected.append(
                {
                    "date": target_date.isoformat(),
                    "score": score_val,
                    "regime": regime_val,
                    "source": "cache",
                    "provider": provider_key,
                    "brief": _compact_text(content, max_chars=500),
                }
            )
            seen_dates.add(target_date.isoformat())
    return selected[:n_past]


def _read_recent_summaries(provider_key: str = "kimi-2.6", n_past: int = 5) -> str:
    """Backward-compatible compact history context; no raw historical reports."""
    ledger = _read_recent_summary_ledger(provider_key=provider_key, n_past=n_past)
    if not ledger:
        return ""
    return json.dumps(ledger, ensure_ascii=False, indent=2, default=str)

def _build_comprehensive_metrics_table(df_stocks, provider_key: str = "kimi-2.6", n_past: int = 7) -> str:
    """Xây dựng bảng số liệu chuỗi thời gian định lượng toàn diện cho n_past phiên gần nhất,
    bao gồm đầu ra của tất cả các công cụ con định lượng."""
    try:
        # 1. Fear & Greed
        fg_metrics = calculate_quant_metrics(df_stocks, window_size=60)
        fg_scored = calculate_risk_score(fg_metrics)
        
        # 2. Manipulation
        df_prices = prep_mani(df_stocks)
        _, result_mani = comp_mani(df_prices, window=60)
        
        # 3. Dispersion
        df_idx = load_custom("vnindex_cache.csv")
        idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
        stock_returns, metrics_disp = calculate_dispersion_metrics(df_stocks, df_idx[idx_col], zscore_type="Rolling", zscore_window=60, dpi_window=60)
        corr = fit_rolling_correlation(stock_returns, window=30, refit_every=5)
        metrics_disp["Ledoit_Correlation"] = corr
        metrics_disp = metrics_disp.dropna(subset=["DPI", "Ledoit_Correlation"])
        
        # 4. Market Breadth
        breadth_df, _ = compute_breadth(df_stocks)
        
        # 5. ESR Monitor
        df_vn30 = load_custom("vn30_cache.csv")
        df_volume = load_volumes()
        _, result_esr, market_states, _ = run_esr_pipeline(
            df_stocks, df_vn30, df_volume=df_volume,
            deposit_rate=PRODUCTION_DEPOSIT_RATE,
            pillar_mode=PRODUCTION_PILLAR_MODE,
            pca_warmup=PRODUCTION_PCA_WARMUP,
            ema_span=PRODUCTION_EMA_SPAN,
            regime_method=PRODUCTION_REGIME_METHOD,
        )
        
        # 6. VaRES & 7. Var-CVaR & RAG (Loop n_past lần vì các hàm này chỉ tính snapshot ngày hiện tại)
        vares_history = []
        var_cvar_history = []
        rag_history = []
        for i in range(n_past):
            sub_df = df_stocks if i == 0 else df_stocks.iloc[:-i]
            vares_history.append(vares_snapshot(sub_df))
            var_cvar_history.append(var_cvar_snapshot(sub_df))
            try:
                from tools.risk_adjusted_growth.report import snapshot as rag_snapshot
                rag_history.append(rag_snapshot(sub_df, load_custom))
            except Exception:
                rag_history.append({"top_bank": "N/A", "top_alpha": 0.0})
        vares_history.reverse()
        var_cvar_history.reverse()
        rag_history.reverse()
        
        # 8. Fed Liquidity
        fed_path = DATA_LAKE / "fed_liquidity_cache.csv"
        df_fed = pd.read_csv(fed_path, parse_dates=["DATE"]).set_index("DATE").sort_index()
        
        # 9. Global FCI
        from tools.global_financial_conditions.quant.metrics import load_cached_gfcm
        gfcm_path = DATA_LAKE / "global_financial_conditions_cache.csv"
        df_gfcm = load_cached_gfcm(gfcm_path)
        
        # 10. VNIBOR
        from tools.vnibor.quant.metrics import load_vnibor_data, process_vnibor_logic
        df_vnibor = process_vnibor_logic(load_vnibor_data())
        
    except Exception as e:
        return f"*Không thể xây dựng bảng số liệu định lượng do thiếu dữ liệu hoặc lỗi tính toán: {e}*"

    # Lấy danh sách các ngày thực tế của n_past phiên giao dịch gần nhất từ df_stocks
    dates = df_stocks.index[-n_past:]
    
    lines = [
        "=== BẢNG SỐ LIỆU CHUỖI THỜI GIAN ĐỊNH LƯỢNG TOÀN DIỆN (T-6 ĐẾN T) ===",
        "| Phiên | F&G Score | Mani Corr/Slope | Disp DPI/Spread Z | Breadth MA20 | ESR SSI | VaRES Stress/Compl. | Var-CVaR ES/xi | Fed Net Liq/Impulse | Global FCI CQS/PC1 | VNIBOR ON/Regime | RAG Top (Alpha) |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|"
    ]
    
    for idx, dt in enumerate(dates):
        days_back = n_past - 1 - idx
        label_date = dt.strftime('%d/%m')
        label = f"T-{days_back} ({label_date})" if days_back > 0 else f"T ({label_date})"
        
        try:
            # 1. F&G
            fg_row = fg_scored.loc[dt]
            fg_val = f"{fg_row['Risk_Score']:.1f}"
        except Exception: fg_val = "N/A"
            
        try:
            # 2. Manipulation
            mani_row = result_mani.loc[dt]
            mani_val = f"{mani_row['Correlation']:.2f}/{mani_row['OLS_Slope']:.2f}"
        except Exception: mani_val = "N/A"
            
        try:
            # 3. Dispersion
            disp_row = metrics_disp.loc[dt]
            disp_val = f"{disp_row['DPI']:.1f}/{disp_row['Spread_Z']:+.2f}"
        except Exception: disp_val = "N/A"
            
        try:
            # 4. Market Breadth
            breadth_row = breadth_df.loc[dt]
            total_stocks = len(df_stocks.columns)
            breadth_val = f"{(breadth_row['> MA20'] / total_stocks * 100.0):.1f}%"
        except Exception: breadth_val = "N/A"
            
        try:
            # 5. ESR
            esr_row = result_esr.loc[dt]
            esr_val = f"{(esr_row['ssi'] * 100.0):.1f}%"
        except Exception: esr_val = "N/A"
            
        try:
            # 6. VaRES
            vares_row = vares_history[idx]
            vares_val = f"{vares_row['stress_index']:.1f}%/{vares_row['complacency_index']:.1f}%"
        except Exception: vares_val = "N/A"
            
        try:
            # 7. Var-CVaR
            var_row = var_cvar_history[idx]
            var_val = f"{(var_row['expected_shortfall'] * 100.0):.1f}%/{var_row['evt_xi']:+.3f}"
        except Exception: var_val = "N/A"
            
        try:
            # 8. Fed Liquidity (tìm ngày gần nhất trong df_fed so với dt)
            fed_idx_date = df_fed.index[df_fed.index <= dt][-1]
            fed_row = df_fed.loc[fed_idx_date]
            fed_val = f"{fed_row['Net Liquidity']/1e3:.1f}T/{fed_row['Impulse']/1e3:+.1f}T"
        except Exception: fed_val = "N/A"
            
        try:
            # 9. Global FCI (tìm ngày gần nhất trong df_gfcm so với dt)
            gfcm_idx_date = df_gfcm.index[df_gfcm.index <= dt][-1]
            gfcm_row = df_gfcm.loc[gfcm_idx_date]
            gfcm_val = f"{gfcm_row['CQS']:.1f}th/{gfcm_row['PC1_smooth']:+.2f}"
        except Exception: gfcm_val = "N/A"
            
        try:
            # 10. VNIBOR (tìm ngày gần nhất trong df_vnibor so với dt)
            vnibor_idx_date = df_vnibor.index[df_vnibor.index <= dt][-1]
            vnibor_row = df_vnibor.loc[vnibor_idx_date]
            vnibor_val = f"{vnibor_row['Overnight']:.2f}%/{vnibor_row['Regime']}"
        except Exception: vnibor_val = "N/A"
            
        try:
            rag_row = rag_history[idx]
            top_bank = rag_row.get("top_bank", "N/A")
            top_alpha = rag_row.get("top_alpha", 0.0)
            if top_bank != "N/A":
                rag_val = f"{top_bank} ({top_alpha*100:.1f}%)"
            else:
                rag_val = "N/A"
        except Exception:
            rag_val = "N/A"

        lines.append(
            f"| {label} | {fg_val} | {mani_val} | {disp_val} | {breadth_val} | {esr_val} | "
            f"{vares_val} | {var_val} | {fed_val} | {gfcm_val} | {vnibor_val} | {rag_val} |"
        )
        
    return "\n".join(lines)

def run_historical_trend_analyst(client, provider_key: str = "kimi-2.6", model: str = None,
                                 raw_history_text: str = "", force: bool = False) -> str:
    """Tóm tắt lịch sử 7 phiên gần nhất thông qua Sub AI CIO."""
    cached = None if force else _read_cache("historical_trend", provider_key)
    if cached:
        return cached

    if not raw_history_text:
        return "Không có dữ liệu lịch sử thô để tóm tắt xu hướng."

    with open(str(ROOT_DIR / "promt" / "historical_trend_promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # Load df_stocks để chạy các hàm định lượng chuỗi thời gian
    df_stocks = load_close_prices()

    # Tạo bảng số liệu chuỗi thời gian định lượng toàn diện cho tất cả các tools con
    metrics_table = _build_comprehensive_metrics_table(df_stocks, provider_key=provider_key, n_past=7)
    if not metrics_table:
        metrics_table = "*Không có dữ liệu chuỗi thời gian định lượng toàn diện từ tools*"

    full_prompt = prompt_template.replace("{historical_reports_raw}", raw_history_text)\
                                 .replace("{historical_ledger}", raw_history_text)\
                                 .replace("{historical_metrics_table}", metrics_table)

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

    res = call_ai(client, sys_p, usr_p, model=model)
    _write_cache("historical_trend", res, provider_key)
    return res

def _clear_all_tool_caches(provider_key: str = "kimi-2.6"):
    """Xoá cache AI text của các công cụ con + executive_summary cho provider_key cụ thể."""
    tool_names = [
        "feargreed", "manipulation", "dispersion", "upside_ratio",
        "bank_valuation_ai", "sentiment_factor_news", "market_breadth", "esr_monitor",
        "va_res", "var_cvar_vnindex",
        "fed_liquidity", "global_financial_conditions", "vnibor", "credit_spread",
        "executive_summary", "telegram_summary", "historical_trend"
    ]
    for tool in tool_names:
        path = _get_cache_path(tool, provider_key)
        if path.exists():
            path.unlink()
            print(f"[Cache Clear] Deleted: {path.name}")
    cache_dir = DATA_LAKE / "daily_cache"
    for path in cache_dir.glob(f"vn100_earnings_health_{provider_key}_*.txt"):
        path.unlink()
        print(f"[Cache Clear] Deleted: {path.name}")
    sidecar_path = _get_humility_rules_path(provider_key)
    if sidecar_path.exists():
        sidecar_path.unlink()
        print(f"[Cache Clear] Deleted: {sidecar_path.name}")

def call_ai(client, system_prompt, user_prompt, model=None, temperature=None):
    response = client.chat.completions.create(
        model=model or AI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=temperature
    )
    return response.choices[0].message.content

# backward-compat alias
call_kimi = call_ai

def run_fear_greed(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("feargreed", provider_key)
    if cached: return cached
    
    metrics_df = calculate_quant_metrics(df_stocks, window_size=60)
    scored_df = calculate_risk_score(metrics_df)
    latest = scored_df.iloc[-1]
    prev = scored_df.iloc[-2]
    score = latest["Risk_Score"]
    date_str = scored_df.index.max().strftime('%d/%m/%Y')
    
    status_text = latest.get("Sentiment_Regime") or ("EXTREME FEAR" if score <= 20 else "FEAR" if score <= 40 else "NEUTRAL / STOCK PICKING" if score < 60 else "GREED" if score < 80 else "EXTREME GREED")
    shock_flag = latest.get("Shock_Regime_Flag", "NONE")
    if shock_flag != "NONE":
        status_text = f"{shock_flag} / {status_text}"

    with open(str(ROOT_DIR / "promt" / "fear greed promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template.replace("{date_str}", date_str)\
                                 .replace("{score}", f"{score:.1f}")\
                                 .replace("{score_delta}", f"{score - prev['Risk_Score']:+.1f}")\
                                 .replace("{status_text}", status_text)\
                                 .replace("{egarch_vol}", f"{latest['Vol_Norm']*100:.1f}")\
                                 .replace("{egarch_delta}", f"{(latest['Vol_Norm'] - prev['Vol_Norm'])*100:+.1f}")\
                                 .replace("{skewness}", f"{latest['Skewness']:.2f}")\
                                 .replace("{down_corr}", f"{latest['Down_Corr_Norm']*100:.1f}")\
                                 .replace("{up_corr}", f"{latest['Up_Corr_Norm']*100:.1f}")
    full_prompt += (
        "\n\n# V2 DIAGNOSTICS\n"
        f"- Methodology: {latest.get('Methodology_Version', FEAR_GREED_METHOD_VERSION)}\n"
        f"- CSV Rank: {latest.get('CSV_Norm', float('nan')):.2f}\n"
        f"- Acute Shock: {latest.get('Acute_Shock', float('nan')):.2f}\n"
        f"- Shock Regime Flag: {shock_flag}\n"
        f"- Signal Confidence: {latest.get('Signal_Confidence', float('nan')):.2f}\n"
        "- Interpretation control: if shock flag is not NONE, do not treat neutral band as ordinary neutral; cap risk-on interpretation.\n"
    )
                                  
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_structured_footer(
        res,
        "fear_greed_methodology",
        [
            f"FearGreed Risk Score: {score:.1f}",
            f"Methodology Version: {latest.get('Methodology_Version', FEAR_GREED_METHOD_VERSION)}",
            f"Sentiment Regime: {status_text}",
            f"Signal Confidence: {latest.get('Signal_Confidence', float('nan')):.2f}",
            f"CSV Rank: {latest.get('CSV_Norm', float('nan')):.2f}",
            f"Acute Shock: {latest.get('Acute_Shock', float('nan')):.2f}",
            f"Shock Regime Flag: {shock_flag}",
            "PCA Method: expanding_point_in_time",
            "PCA Full-History Fit: 0",
            "PCA Refit Every Sessions: 21",
        ],
    )
    res = _append_direct_metrics(
        res,
        "fear_greed",
        {
            "fear_greed_score": score,
            "sentiment_regime": status_text,
            "signal_confidence": latest.get("Signal_Confidence"),
            "acute_shock": latest.get("Acute_Shock"),
            "csv_rank": latest.get("CSV_Norm"),
            "shock_regime_flag": shock_flag,
        },
    )
    _write_cache("feargreed", res, provider_key)
    return res

def run_manipulation(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("manipulation", provider_key)
    if cached: return cached

    df_idx = load_custom("vnindex_cache.csv")
    idx_col = MANIPULATION_TARGET if MANIPULATION_TARGET in df_idx.columns else df_idx.columns[0]
    df_prices = prep_mani(df_stocks, target_series=df_idx[idx_col])
    weights_df, result_df = comp_mani(df_prices, window=60)
    # Rolling 60-session event-study anchor — mirror UI default in tools/manipulation/page.py:71
    t0_dt = pd.Timestamp(result_df.index[-60] if len(result_df) >= 60 else result_df.index[0])
    re_df = classify_regime(result_df, threshold=0.15, t0_dt=t0_dt)

    date_str = result_df.index.max().strftime('%d/%m/%Y')
    latest = result_df.iloc[-1]

    slope_val = latest["OLS_Slope"]
    # Dùng percentileofscore toàn lịch sử (same method as UI charts.py) thay vì PR_Slope rolling-60
    slope_pr = percentileofscore(result_df["OLS_Slope"].dropna(), slope_val, kind="rank")
    slope_status = "🔴 Cao" if slope_pr >= 80 else "🟢 Thấp" if slope_pr <= 20 else "🟡 Trung bình"

    corr_val = latest["Correlation"]
    # Dùng percentileofscore toàn lịch sử (same method as UI charts.py) thay vì PR_Corr rolling-60
    corr_pr = percentileofscore(result_df["Correlation"].dropna(), corr_val, kind="rank")
    corr_status = "🔴 Rất chặt" if corr_pr >= 80 else "🟢 Phân kỳ" if corr_pr <= 20 else "🟡 Lỏng"

    t0_str = t0_dt.strftime('%d/%m/%Y')
    regime = re_df["Regime"].iloc[-1] if not re_df.empty else "N/A"
    d_corr = re_df["Delta_PR_Corr"].iloc[-1] if not re_df.empty else 0
    d_slope = re_df["Delta_PR_Slope"].iloc[-1] if not re_df.empty else 0

    momentum_str = f"ΔCorr = {d_corr:.2f}, ΔSlope = {d_slope:.2f}"

    # ── Inject giá real-time VIC/VHM/VRE + VNINDEX để chống AI hallucinate
    # mức giá cũ (vd. "VIC mất 45,000" trong khi VIC hiện ~200k). df_prices từ
    # prep_mani() có sẵn 4 cột [VIC, VHM, VRE, VNINDEX].
    # Cổ phiếu: market_data.csv lưu theo nghìn VND → *1000 ra VND đầy đủ.
    # VNINDEX: đơn vị "điểm" — KHÔNG nhân 1000.
    def _fmt_stock_price(value: float) -> str:
        if pd.isna(value) or value <= 0:
            return "N/A"
        return f"{value:.2f} (≈ {int(value * 1000):,} VND)"

    def _fmt_index_value(value: float) -> str:
        if pd.isna(value) or value <= 0:
            return "N/A"
        return f"{value:,.2f} điểm"

    last_prices = df_prices.iloc[-1]
    vic_close = _fmt_stock_price(last_prices.get("VIC", float("nan")))
    vhm_close = _fmt_stock_price(last_prices.get("VHM", float("nan")))
    vre_close = _fmt_stock_price(last_prices.get("VRE", float("nan")))
    vnindex_close = _fmt_index_value(last_prices.get(MANIPULATION_TARGET, float("nan")))

    with open(str(ROOT_DIR / "promt" / "manipulation promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("{date_str}", date_str)\
                                 .replace("{slope_val}", f"{slope_val:.2f}")\
                                 .replace("{slope_pr}", f"{slope_pr:.1f}")\
                                 .replace("{slope_status}", slope_status)\
                                 .replace("{corr_val}", f"{corr_val:.2f}")\
                                 .replace("{corr_pr}", f"{corr_pr:.1f}")\
                                 .replace("{corr_status}", corr_status)\
                                 .replace("{t0_str}", t0_str)\
                                 .replace("{regime}", regime)\
                                 .replace("{momentum_str}", momentum_str)\
                                 .replace("{vic_close}", vic_close)\
                                 .replace("{vhm_close}", vhm_close)\
                                 .replace("{vre_close}", vre_close)\
                                 .replace("{vnindex_close}", vnindex_close)
    full_prompt += (
        "\n\n# V2 DIAGNOSTICS\n"
        f"- Methodology: {MANIPULATION_METHOD_VERSION}\n"
        f"- Target: {MANIPULATION_TARGET}, not VN30F1M.\n"
        "- Interpretation: slope/correlation measure VIN composite coupling with cash VNINDEX, not futures trading signal.\n"
        "- Return handling: pct_change(fill_method=None), log1p returns, rows require VIC/VHM/VRE/VNINDEX all valid.\n"
    )

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res += (
        "\n\n---\n"
        f"manipulation_methodology: {MANIPULATION_METHOD_VERSION}; "
        f"target={MANIPULATION_TARGET}; not_futures=true; "
        f"slope={float(slope_val):.3f}; corr={float(corr_val):.3f}; regime={regime}"
    )
    res = _append_direct_metrics(
        res,
        "manipulation",
        {
            "manip_slope": slope_val,
            "manip_corr": corr_val,
            "manip_slope_percentile": slope_pr,
            "manip_corr_percentile": corr_pr,
            "regime": regime,
            "delta_corr_percentile": d_corr,
            "delta_slope_percentile": d_slope,
        },
    )
    _write_cache("manipulation", res, provider_key)
    return res

def run_dispersion(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("dispersion", provider_key)
    if cached: return cached
    
    df_idx = load_custom("vnindex_cache.csv")
    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    index_series = df_idx[idx_col]
    
    stock_returns, metrics = calculate_dispersion_metrics(df_stocks, index_series, zscore_type="Rolling", zscore_window=60, dpi_window=60)
    corr = fit_rolling_correlation(stock_returns, window=30, refit_every=5)
    metrics["Ledoit_Correlation"] = corr
    metrics["Macro_Regime"] = determine_macro_regime(metrics)
    metrics = metrics.dropna(subset=["DPI", "Ledoit_Correlation"])
    dispersion_summary = summarize_dispersion_state(metrics)
    
    latest = metrics.iloc[-1]
    date_str = metrics.index.max().strftime('%d/%m/%Y')
    
    spread_val = latest.get("Spread", 0) * 100 * (252**0.5)
    spread_z = latest.get("Spread_Z", 0)
    dpi_val = latest.get("DPI", 0)
    corr_val = latest.get("Ledoit_Correlation", 0)
    
    cs_skew = latest.get("CS_Skewness", "N/A")
    if isinstance(cs_skew, (int, float)) and not pd.isna(cs_skew): cs_skew = f"{cs_skew:+.2f}"
    cs_kurt = latest.get("CS_Kurtosis", "N/A")
    if isinstance(cs_kurt, (int, float)) and not pd.isna(cs_kurt): cs_kurt = f"{cs_kurt:.2f}"

    with open(str(ROOT_DIR / "promt" / "dispersion promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("{date_str}", date_str)\
                                 .replace("{spread_val}", f"{spread_val:.2f}")\
                                 .replace("{spread_z}", f"{spread_z:+.2f}")\
                                 .replace("{dpi_val}", f"{dpi_val:.1f}")\
                                 .replace("{corr_val}", f"{corr_val:.3f}")\
                                 .replace("{cs_skew}", cs_skew)\
                                 .replace("{cs_kurt}", cs_kurt)
    full_prompt += (
        "\n\n# V2 DIAGNOSTICS\n"
        f"- Macro regime: {dispersion_summary['macro_regime']}\n"
        f"- Broad stress score: {dispersion_summary['broad_stress_score']:.1f}/100 "
        f"({dispersion_summary['broad_stress_level']})\n"
        f"- CSAD_Z / CSSD_Z: {dispersion_summary['csad_z']:+.2f} / {dispersion_summary['cssd_z']:+.2f}\n"
        f"- Downside participation: {dispersion_summary['downside_participation']:.1f}%\n"
        "- Return method: no forward-fill; bad ticks >50% daily absolute return treated as missing.\n"
    )

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_structured_footer(
        res,
        "dispersion_methodology",
        [
            f"Methodology Version: {dispersion_summary['methodology_version']}",
            f"Macro Regime: {dispersion_summary['macro_regime']}",
            f"Broad Stress Score: {dispersion_summary['broad_stress_score']:.1f}",
            f"Broad Stress Level: {dispersion_summary['broad_stress_level']}",
            f"CSAD Z: {dispersion_summary['csad_z']:+.2f}",
            f"CSSD Z: {dispersion_summary['cssd_z']:+.2f}",
            f"Downside Participation: {dispersion_summary['downside_participation']:.1f}%",
            "Returns Fill Method: none",
            "Bad Tick Filter: abs daily return >50% set to missing",
        ],
    )
    res = _append_direct_metrics(
        res,
        "dispersion",
        {
            "dispersion_spread_z": spread_z,
            "dispersion_dpi_pct": dpi_val,
            "dispersion_avg_corr": corr_val,
            "dispersion_broad_stress_score": dispersion_summary["broad_stress_score"],
            "downside_participation_pct": dispersion_summary["downside_participation"],
            "macro_regime": dispersion_summary["macro_regime"],
            "broad_stress_level": dispersion_summary["broad_stress_level"],
        },
    )
    _write_cache("dispersion", res, provider_key)
    return res

def run_upside_ratio(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("upside_ratio", provider_key)
    if cached: return cached
    
    data = build_breadth_series(df_stocks, upside_x=2.0, downside_y=-2.0, lookback_days=90)
    breadth_summary = summarize_breadth_state(data)
    up_tuple = run_hybrid_ensemble_mc(
        data["raw_upside"], days_to_sim=20, num_sims=5000, seed=DEFAULT_MC_SEED
    )
    dn_tuple = run_hybrid_ensemble_mc(
        data["raw_downside"], days_to_sim=20, num_sims=5000, seed=DEFAULT_MC_SEED + 1
    )
    
    p5_up, p25_up, p50_up, p75_up, p95_up, phi_up, mu_up, _, _ = up_tuple
    p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, phi_dn, mu_dn, _, _ = dn_tuple
    
    regime_up = (
        "📈 Momentum (Đà Mua)" if phi_up > 0.1
        else "🔄 Mean-reversion (Đảo chiều Mua)" if phi_up < -0.1
        else "🎲 Random Walk (Nhiễu Mua)"
    )
    regime_dn = (
        "🩸 Momentum (Đà Bán)" if phi_dn > 0.1
        else "🔄 Mean-reversion (Đảo chiều Bán)" if phi_dn < -0.1
        else "🎲 Random Walk (Nhiễu Bán)"
    )
    
    with open(str(ROOT_DIR / "promt" / "upside ratio promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("{upside_current}", f"{data['raw_upside'].values[-1]:.2f}")\
                                 .replace("{upside_mu}", f"{mu_up*100:.2f}")\
                                 .replace("{upside_phi}", f"{phi_up:.3f}")\
                                 .replace("{upside_regime}", regime_up)\
                                 .replace("{downside_current}", f"{data['raw_downside'].values[-1]:.2f}")\
                                 .replace("{downside_mu}", f"{mu_dn*100:.2f}")\
                                 .replace("{downside_phi}", f"{phi_dn:.3f}")\
                                 .replace("{downside_regime}", regime_dn)\
                                 .replace("{sim_days}", "19")\
                                 .replace("{p95_up}", f"{p95_up[-1]:.2f}")\
                                 .replace("{p95_dn}", f"{p95_dn[-1]:.2f}")
    full_prompt += (
        "\n\n# V2 DIAGNOSTICS\n"
        f"- Methodology: {breadth_summary['methodology_version']}\n"
        f"- Breadth regime: {breadth_summary['breadth_regime']}\n"
        f"- Breadth stress score: {breadth_summary['breadth_stress_score']:.1f}/100 "
        f"({breadth_summary['breadth_stress_level']})\n"
        f"- Downside rank: {breadth_summary['downside_rank']:.2f}; "
        f"upside rank: {breadth_summary['upside_rank']:.2f}\n"
        f"- Net sell pressure: {breadth_summary['net_pressure']:+.1f}pp; "
        f"MA5: {breadth_summary['ma5_net_pressure']:+.1f}pp\n"
        "- Interpretation control: downside stress dominates; MC paths are stress scenarios, not allocation authority.\n"
    )

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_structured_footer(
        res,
        "upside_ratio_methodology",
        [
            f"MC Seed Upside: {DEFAULT_MC_SEED}",
            f"MC Seed Downside: {DEFAULT_MC_SEED + 1}",
            "MC Simulations Per Side: 5000",
            "MC Deterministic: 1",
            f"Breadth Regime: {breadth_summary['breadth_regime']}",
            f"Breadth Stress Score: {breadth_summary['breadth_stress_score']:.1f}",
            f"Downside Rank: {breadth_summary['downside_rank']:.2f}",
            f"Net Sell Pressure: {breadth_summary['net_pressure']:+.1f} pp",
            "MC Interpretation: scenario_diagnostic_not_allocation_authority",
        ],
    )
    res = _append_direct_metrics(
        res,
        "upside_ratio",
        {
            "upside_current_pct": data["raw_upside"].values[-1],
            "downside_current_pct": data["raw_downside"].values[-1],
            "p95_upside_pct": p95_up[-1],
            "p95_downside_pct": p95_dn[-1],
            "phi_up": phi_up,
            "phi_down": phi_dn,
            "breadth_stress_score": breadth_summary["breadth_stress_score"],
            "net_sell_pressure_pct": breadth_summary["net_pressure"],
            "breadth_regime": breadth_summary["breadth_regime"],
        },
    )
    _write_cache("upside_ratio", res, provider_key)
    return res

def run_bank_valuation(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("bank_valuation_ai", provider_key)
    if cached: return cached

    try:
        volumes = load_volumes()
        valuation_df, _ = run_bank_valuation_pipeline(close_prices=df_stocks, volumes=volumes)
    except Exception as exc:
        return f"DATA INSUFFICIENT - Bank Valuation feed unavailable: {exc}"

    focus_question = (
        "Tóm tắt feed Bank Valuation cho AI CIO: valuation breadth regime của nhóm ngân hàng, "
        "best/worst valuation gaps, fair/undervalued candidates, overvalued/value-trap risks, "
        "market confirmation, data quality, và các cảnh báo cần dùng trong allocation."
    )
    sys_p, usr_p = build_bank_valuation_ai_prompt(
        valuation_df,
        ohlcv_source="quant_platform_market_data",
        focus_question=focus_question,
    )

    res = call_ai(client, sys_p, usr_p, model=model)
    valuation_regime = calculate_bank_valuation_regime(valuation_df)
    best = (
        valuation_df.sort_values("valuation_gap_pct", ascending=False).iloc[0]
        if not valuation_df.empty and "valuation_gap_pct" in valuation_df
        else pd.Series(dtype=object)
    )
    worst = (
        valuation_df.sort_values("valuation_gap_pct", ascending=True).iloc[0]
        if not valuation_df.empty and "valuation_gap_pct" in valuation_df
        else pd.Series(dtype=object)
    )
    res = _append_direct_metrics(
        res,
        "bank_valuation",
        {
            "eligible_banks": valuation_regime.eligible_banks,
            "bank_valuation_breadth_score": valuation_regime.bank_valuation_breadth_score,
            "median_valuation_gap_pct": valuation_regime.median_valuation_gap,
            "valuation_regime": valuation_regime.regime_label,
            "overvalued_count": valuation_regime.overvalued_count,
            "fair_count": valuation_regime.fair_count,
            "undervalued_count": valuation_regime.undervalued_count,
            "best_ticker": best.get("ticker"),
            "best_valuation_gap_pct": best.get("valuation_gap_pct"),
            "worst_ticker": worst.get("ticker"),
            "worst_valuation_gap_pct": worst.get("valuation_gap_pct"),
        },
    )
    _write_cache("bank_valuation_ai", res, provider_key)
    return res


def run_sentiment_factor_news(client, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("sentiment_factor_news", provider_key)
    if cached: return cached

    try:
        sys_p, usr_p = build_sentiment_factor_news_ai_prompt()
    except Exception as exc:
        res = f"DATA INSUFFICIENT - Sentiment Factor From News feed unavailable: {exc}"
        _write_cache("sentiment_factor_news", res, provider_key)
        return res

    res = call_ai(client, sys_p, usr_p, model=model)
    direct_metrics: dict[str, Any] = {}
    for window in ("1d", "7d", "30d"):
        snap = sentiment_factor_news_snapshot(window=window)
        if snap.get("status") != "ok":
            continue
        suffix = window
        direct_metrics[f"news_macro_composite_{suffix}"] = snap.get("macro_composite")
        direct_metrics[f"news_confidence_{suffix}"] = snap.get("macro_composite_prob_pos")
        direct_metrics[f"news_count_{suffix}"] = snap.get("news_count")
        direct_metrics[f"news_regime_{suffix}"] = snap.get("regime")
        direct_metrics[f"news_source_counts_{suffix}"] = snap.get("source_counts")
    if direct_metrics:
        direct_metrics["news_macro_composite"] = direct_metrics.get("news_macro_composite_1d")
        direct_metrics["news_confidence"] = direct_metrics.get("news_confidence_1d")
        direct_metrics["news_count"] = direct_metrics.get("news_count_1d")
        res = _append_direct_metrics(res, "sentiment_factor_news", direct_metrics)
    _write_cache("sentiment_factor_news", res, provider_key)
    return res


def run_risk_adjusted_growth(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("risk_adjusted_growth", provider_key)
    if cached: return cached

    try:
        from tools.risk_adjusted_growth.quant.data_prep import (
            build_base_table_from_statistics,
            risk_adjusted_growth_source_signature,
            STATISTICS_JSON_DIR,
            FINANCIAL_REPORT_JSON_DIR
        )
        from tools.risk_adjusted_growth.quant.scoring import compute_scores

        source_signature = risk_adjusted_growth_source_signature(
            STATISTICS_JSON_DIR,
            FINANCIAL_REPORT_JSON_DIR,
        )
        price_row = df_stocks.ffill().iloc[-1].to_dict()
        df_base = build_base_table_from_statistics(
            STATISTICS_JSON_DIR,
            financial_report_dir=FINANCIAL_REPORT_JSON_DIR,
            price_row=price_row,
        )
        df_result = compute_scores(
            df_base=df_base,
            k_value=1.0,
            coe_decimal=0.14,
            bvps_change_pct=0.0,
            pb_penalty_pct=0.0,
        )
    except Exception as exc:
        res = f"DATA INSUFFICIENT - Risk-Adjusted Growth feed unavailable: {exc}"
        _write_cache("risk_adjusted_growth", res, provider_key)
        return res

    try:
        with open(str(ROOT_DIR / "promt" / "risk adjusted growth promt.md"), "r", encoding="utf-8") as f:
            prompt_template = f.read()

        ticker_col = "Ticker" if "Ticker" in df_result.columns else "Ngân hàng"
        top_alpha = df_result.nlargest(3, "Economic Alpha")
        top_alpha_str = ", ".join([
            (
                f"{i+1}. {row[ticker_col]} "
                f"(Alpha {row['Economic Alpha']*100:.1f}%, "
                f"P/B {row['P/B Gốc']:.2f}, "
                f"ROE {row['Geomean ROE']*100:.1f}%, "
                f"σROE {row['Stdev ROE']*100:.1f}%, "
                f"Payout {row['Cash Payout Ratio']*100:.1f}%)"
            )
            for i, row in enumerate(top_alpha.to_dict('records'))
        ])

        bottom_alpha = df_result.nsmallest(3, "Economic Alpha")
        bottom_alpha_str = ", ".join([
            (
                f"{i+1}. {row[ticker_col]} "
                f"(Alpha {row['Economic Alpha']*100:.1f}%, "
                f"P/B {row['P/B Gốc']:.2f}, "
                f"ROE {row['Geomean ROE']*100:.1f}%, "
                f"σROE {row['Stdev ROE']*100:.1f}%, "
                f"Payout {row['Cash Payout Ratio']*100:.1f}%)"
            )
            for i, row in enumerate(bottom_alpha.to_dict('records'))
        ])

        full_prompt = prompt_template.replace("{k_scenario}", "Trung lập")\
                                     .replace("{k_value}", "1.0")\
                                     .replace("{coe_input}", "14.0")\
                                     .replace("{bvps_change_pct}", "0.0")\
                                     .replace("{pb_penalty_pct}", "0.0")\
                                     .replace("{top_alpha_str}", top_alpha_str)\
                                     .replace("{bottom_alpha_str}", bottom_alpha_str)

        parts = full_prompt.split("# INPUT DATA")
        system_prompt = parts[0].strip()
        user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    except Exception as exc:
        res = f"DATA INSUFFICIENT - Error processing Risk-Adjusted Growth prompt: {exc}"
        _write_cache("risk_adjusted_growth", res, provider_key)
        return res

    res = call_ai(client, system_prompt, user_prompt, model=model)
    top_row = top_alpha.iloc[0]
    res = _append_direct_metrics(
        res,
        "risk_adjusted_growth",
        {
            "top_ticker": top_row[ticker_col],
            "top_economic_alpha_pct": float(top_row["Economic Alpha"]) * 100.0,
            "median_economic_alpha_pct": float(df_result["Economic Alpha"].median()) * 100.0,
            "positive_alpha_count": int((df_result["Economic Alpha"] > 0).sum()),
            "bank_count": int(len(df_result)),
            "top_tickers": top_alpha[ticker_col].astype(str).tolist(),
            "bottom_tickers": bottom_alpha[ticker_col].astype(str).tolist(),
            "scenario_k": 1.0,
            "coe_pct": 14.0,
            "source_signature": source_signature,
        },
    )
    _write_cache("risk_adjusted_growth", res, provider_key)
    return res


def run_market_breadth(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("market_breadth", provider_key)
    if cached: return cached
    
    breadth, masks = compute_breadth(df_stocks)
    if breadth.empty:
        return "Không đủ dữ liệu Market Breadth."
    
    latest_date = breadth.index[-1]
    latest = breadth.iloc[-1]
    date_str = latest_date.strftime('%d/%m/%Y')
    total_count = len(masks["> MA20"].loc[latest_date])
    
    ma20_count = int(latest["> MA20"])
    ma20_pct = (ma20_count / total_count * 100.0) if total_count > 0 else 0.0
    ma60_count = int(latest["> MA60"])
    ma60_pct = (ma60_count / total_count * 100.0) if total_count > 0 else 0.0
    ma125_count = int(latest["> MA125"])
    ma125_pct = (ma125_count / total_count * 100.0) if total_count > 0 else 0.0
    ma252_count = int(latest["> MA252"])
    ma252_pct = (ma252_count / total_count * 100.0) if total_count > 0 else 0.0
    
    # Top volume leaders (optional — skip if no volume cache)
    valid_ma20 = masks["> MA20"].loc[latest_date]
    valid_ma20_stocks = valid_ma20[valid_ma20].index
    valid_ma252 = masks["> MA252"].loc[latest_date]
    valid_ma252_stocks = valid_ma252[valid_ma252].index
    
    top_ma20_str = ", ".join(valid_ma20_stocks.tolist()[:10])
    top_ma252_str = ", ".join(valid_ma252_stocks.tolist()[:10])
    
    with open(str(ROOT_DIR / "promt" / "Market Breadth promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template
    full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
    full_prompt = full_prompt.replace("[Nhập số lượng, VD: 215 mã]", f"{total_count} mã")
    full_prompt = full_prompt.replace("Số mã > MA20: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA20: {ma20_count} mã (Chiếm {ma20_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA60: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA60: {ma60_count} mã (Chiếm {ma60_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA125: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA125: {ma125_count} mã (Chiếm {ma125_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA252: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA252: {ma252_count} mã (Chiếm {ma252_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("[Liệt kê mã, VD: HPG, SSI, NVL, DIG...]", top_ma20_str, 1)
    full_prompt = full_prompt.replace("[Liệt kê mã, VD: VCB, FPT, ACB...]", top_ma252_str, 1)
    
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_direct_metrics(
        res,
        "market_breadth",
        {
            "breadth_ma20_pct": ma20_pct,
            "breadth_ma60_pct": ma60_pct,
            "breadth_ma125_pct": ma125_pct,
            "breadth_ma252_pct": ma252_pct,
            "above_ma20_count": ma20_count,
            "above_ma60_count": ma60_count,
            "above_ma125_count": ma125_count,
            "above_ma252_count": ma252_count,
            "breadth_universe_size": total_count,
            "snapshot_date": date_str,
        },
    )
    _write_cache("market_breadth", res, provider_key)
    return res

def run_esr_monitor(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("esr_monitor", provider_key)
    if cached: return cached
    
    df_vn30 = load_custom("vn30_cache.csv")
    # Volume thật từ market_volume.csv (sau khi user chạy update_data.py phiên bản mới).
    # Nếu file chưa tồn tại → load_volumes() trả None, pipeline tự fallback proxy + log warning.
    df_volume = load_volumes()
    # AI CIO AUTO/Manual: dùng PRODUCTION_REGIME_METHOD (single source of truth).
    # AI CIO chỉ đọc regime của ngày hiện tại → look-ahead bias không leak.
    # Đồng bộ với ESR Monitor LIVE default và report.py snapshot.
    pillars, result, market_states, threshold = run_esr_pipeline(
        df_stocks, df_vn30,
        df_volume=df_volume,
        deposit_rate=PRODUCTION_DEPOSIT_RATE,
        pillar_mode=PRODUCTION_PILLAR_MODE,
        pca_warmup=PRODUCTION_PCA_WARMUP,
        ema_span=PRODUCTION_EMA_SPAN,
        regime_method=PRODUCTION_REGIME_METHOD,
    )

    if pillars.empty or result.ssi.dropna().empty:
        return "Không đủ dữ liệu ESR Monitor."

    last_ssi = result.ssi.dropna().iloc[-1]
    last_idx = pillars['INDEX_Close'].dropna().iloc[-1]
    last_evr = result.pca_concentration.dropna().iloc[-1]
    last_w = result.weights_history.dropna().iloc[-1]
    date_str = pillars.index[-1].strftime('%d/%m/%Y')

    ssi_pct = last_ssi * 100
    evr_pct = last_evr * 100

    sorted_w = last_w.sort_values(ascending=False)
    w1_name = sorted_w.index[0]
    w1_val = sorted_w.iloc[0] * 100
    w2_name = sorted_w.index[1]
    w2_val = sorted_w.iloc[1] * 100
    w3_name = sorted_w.index[2]
    w3_val = sorted_w.iloc[2] * 100
    
    # Determine status
    if market_states is not None and not market_states.empty:
        hmm_ok = True
        current_key = market_states.dropna().iloc[-1]
        from tools.esr_monitor.quant.metrics import MARKET_STATES as MS
        if current_key in MS:
            status = MS[current_key]['label']
        else:
            status = current_key
    else:
        hmm_ok = False
        status = "SAFE" if last_ssi < 0.5 else "WARNING" if last_ssi < 0.8 else "CRITICAL"

    ma_status = "nằm trên" if last_idx >= pillars['INDEX_Close'].rolling(125).mean().iloc[-1] else "nằm dưới"

    with open(str(ROOT_DIR / "promt" / "ESR monitor promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template
    full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
    full_prompt = full_prompt.replace("[Nhập điểm số VN30]", f"{last_idx:.2f}")
    full_prompt = full_prompt.replace("[nằm trên/nằm dưới]", ma_status)
    full_prompt = full_prompt.replace("[20/60/125/252]", "125")
    full_prompt = full_prompt.replace("[Nhập %, VD: 85.5%]", f"{ssi_pct:.1f}%")
    full_prompt = full_prompt.replace("[SAFE / WARNING / CRITICAL]", status)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w1_name} ({w1_val:.0f}%)", 1)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w2_name} ({w2_val:.0f}%)", 1)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w3_name} ({w3_val:.0f}%)", 1)
    # Extended
    full_prompt = full_prompt.replace("[PCA_EVR]", f"{evr_pct:.1f}%")
    full_prompt = full_prompt.replace("[Market State]", status)
    full_prompt = full_prompt.replace("[Pillar Mode]", PRODUCTION_PILLAR_MODE)
    if "[Threshold]" in full_prompt:
        full_prompt = full_prompt.replace("[Threshold]", f"{threshold:.3f}" if threshold is not None else "N/A")

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_direct_metrics(
        res,
        "esr_monitor",
        {
            "ssi_pct": ssi_pct,
            "pca_concentration_pct": evr_pct,
            "market_state": status,
            "hmm_available": hmm_ok,
            "production_regime_method": PRODUCTION_REGIME_METHOD,
            "production_pillar_mode": PRODUCTION_PILLAR_MODE,
            "top_pillar": w1_name,
            "top_pillar_weight_pct": w1_val,
        },
    )
    _write_cache("esr_monitor", res, provider_key)
    return res

def run_va_res(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("va_res", provider_key)
    if cached: return cached
    
    snap = vares_snapshot(df_stocks)
    
    with open(str(ROOT_DIR / "promt" / "va_res_promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template.replace("[Nhập ngày]", snap['date'])\
                                 .replace("[Stress Index %]", f"{snap['stress_index']:.2f}%")\
                                 .replace("[Breached Count]", str(snap.get('breached_count', 0)))\
                                 .replace("[Top 3 Crash]", ", ".join(snap['top_3_crash']))\
                                 .replace("[Complacency Index %]", f"{snap['complacency_index']:.2f}%")\
                                 .replace("[Mispriced Count]", str(snap.get('mispriced_count', 0)))\
                                 .replace("[Top 3 Mispriced]", ", ".join(snap['top_3_mispriced']))
    full_prompt += (
        "\n\n# V2 DIAGNOSTICS\n"
        f"- Methodology: {snap.get('methodology_version', 'N/A')}\n"
        f"- VaRES regime: {snap.get('vares_regime', 'N/A')}\n"
        f"- Stress level: {snap.get('stress_level', 'N/A')} "
        f"({snap.get('breached_count', 0)}/{snap.get('valid_vn30_count', 'N/A')} valid VN30 breached)\n"
        f"- Complacency level: {snap.get('complacency_level', 'N/A')} "
        f"({snap.get('mispriced_count', 0)}/{snap.get('valid_market_count', 'N/A')} valid market names mispriced)\n"
        "- Return handling: prior-window VaR/ES, no look-ahead, no forward-fill, abs daily return > 50% treated as bad tick.\n"
        "- Market proxy: VNINDEX if available; otherwise equal-weight normalized proxy.\n"
    )
    
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res += (
        "\n\n---\n"
        f"vares_methodology: {snap.get('methodology_version', 'N/A')}; "
        f"regime={snap.get('vares_regime', 'N/A')}; "
        f"stress={snap.get('stress_index', float('nan')):.2f}% "
        f"({snap.get('breached_count', 0)}/{snap.get('valid_vn30_count', 'N/A')}); "
        f"complacency={snap.get('complacency_index', float('nan')):.2f}% "
        f"({snap.get('mispriced_count', 0)}/{snap.get('valid_market_count', 'N/A')}); "
        "prior_window_no_lookahead=true; bad_tick_abs_return_gt_50pct=null"
    )
    res = _append_direct_metrics(
        res,
        "va_res",
        {
            "vares_stress_index_pct": snap.get("stress_index"),
            "vares_complacency_pct": snap.get("complacency_index"),
            "vares_breach_count": snap.get("breached_count"),
            "vares_mispriced_count": snap.get("mispriced_count"),
            "valid_vn30_count": snap.get("valid_vn30_count"),
            "valid_market_count": snap.get("valid_market_count"),
            "vares_regime": snap.get("vares_regime"),
            "stress_level": snap.get("stress_level"),
            "complacency_level": snap.get("complacency_level"),
        },
    )
    _write_cache("va_res", res, provider_key)
    return res

def run_var_cvar_vnindex(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("var_cvar_vnindex", provider_key)
    if cached: return cached

    snap = var_cvar_snapshot(df_stocks)

    with open(str(ROOT_DIR / "promt" / "var_cvar_vnindex_promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("[Nhập ngày]", snap['date'])\
                                 .replace("[Giá VNINDEX]", f"{snap['vnindex_price']:,.2f}")\
                                 .replace("[σ 30 ngày]", f"{snap['stdev_30']*100:.2f}%")\
                                 .replace("[Parametric VaR]", f"{snap['parametric_var']*100:.2f}%")\
                                 .replace("[Historical VaR]", f"{snap['historical_var']*100:.2f}%")\
                                 .replace("[Expected Shortfall]", f"{snap['expected_shortfall']*100:.2f}%")\
                                 .replace("[ES - VaR Spread]", f"{snap['es_var_spread']*100:.2f}%")

    # EVT placeholders — fallback "N/A" nếu data chưa đủ 3 năm
    if snap.get("evt_available"):
        xi_label = (
            "fat tail (đuôi cực dày)" if snap['evt_xi'] > 0.30
            else "heavy tail (đuôi nặng)" if snap['evt_xi'] > 0.15
            else "near-Gaussian (đuôi nhẹ)"
        )
        full_prompt = full_prompt\
            .replace("[EVT VaR 99%]", f"{snap['evt_var_99']*100:.2f}%")\
            .replace("[EVT VaR 99.5%]", f"{snap['evt_var_995']*100:.2f}%")\
            .replace("[EVT ES 99%]", f"{snap['evt_es_99']*100:.2f}%")\
            .replace("[EVT Xi]", _format_evt_xi_summary(snap, xi_label))\
            .replace("[Hill Index]", f"{snap['hill_index']:+.3f}")\
            .replace("[EVT N Exceed]", str(snap['evt_n_exceed']))
        if snap.get("evt_sensitivity_available"):
            stable_flag = 1 if snap.get("evt_sensitivity_stable") else 0
            full_prompt = full_prompt\
                .replace("[EVT Xi Min]", f"{snap['evt_sensitivity_xi_min']:+.3f}")\
                .replace("[EVT Xi Max]", f"{snap['evt_sensitivity_xi_max']:+.3f}")\
                .replace("[EVT Xi Range]", f"{snap['evt_sensitivity_xi_range']:.3f}")\
                .replace("[EVT VaR99 Range]", f"{abs(snap['evt_sensitivity_var99_range'])*100:.2f}pp")\
                .replace("[EVT ES99 Range]", f"{abs(snap['evt_sensitivity_es99_range'])*100:.2f}pp")\
                .replace("[EVT Threshold Stable]", str(stable_flag))\
                .replace("[EVT Sensitivity Status]", str(snap.get("evt_sensitivity_status", "threshold_sensitive")))
        else:
            for placeholder in [
                "[EVT Xi Min]", "[EVT Xi Max]", "[EVT Xi Range]",
                "[EVT VaR99 Range]", "[EVT ES99 Range]",
                "[EVT Threshold Stable]", "[EVT Sensitivity Status]",
            ]:
                full_prompt = full_prompt.replace(placeholder, "N/A")
        if snap.get("evt_interval_available"):
            full_prompt = full_prompt\
                .replace("[EVT Interval Method]", str(snap.get("evt_interval_method", "gpd_random_walk_mcmc")))\
                .replace("[EVT MCMC Acceptance]", f"{snap['evt_interval_acceptance_rate']:.1%}")\
                .replace("[EVT MCMC Samples]", str(snap.get("evt_interval_samples", 0)))\
                .replace("[EVT Xi P05]", f"{snap['evt_xi_p05']:+.3f}")\
                .replace("[EVT Xi P50]", f"{snap['evt_xi_p50']:+.3f}")\
                .replace("[EVT Xi P95]", f"{snap['evt_xi_p95']:+.3f}")\
                .replace("[EVT VaR99 P05]", f"{snap['evt_var99_p05']*100:.2f}%")\
                .replace("[EVT VaR99 P50]", f"{snap['evt_var99_p50']*100:.2f}%")\
                .replace("[EVT VaR99 P95]", f"{snap['evt_var99_p95']*100:.2f}%")\
                .replace("[EVT ES99 P05]", f"{snap['evt_es99_p05']*100:.2f}%")\
                .replace("[EVT ES99 P50]", f"{snap['evt_es99_p50']*100:.2f}%")\
                .replace("[EVT ES99 P95]", f"{snap['evt_es99_p95']*100:.2f}%")
        else:
            for placeholder in [
                "[EVT Interval Method]", "[EVT MCMC Acceptance]", "[EVT MCMC Samples]",
                "[EVT Xi P05]", "[EVT Xi P50]", "[EVT Xi P95]",
                "[EVT VaR99 P05]", "[EVT VaR99 P50]", "[EVT VaR99 P95]",
                "[EVT ES99 P05]", "[EVT ES99 P50]", "[EVT ES99 P95]",
            ]:
                full_prompt = full_prompt.replace(placeholder, "N/A")
    else:
        # Data < 756 ngày — bỏ EVT fields, AI prompt vẫn chạy với classic metrics
        for placeholder in [
            "[EVT VaR 99%]", "[EVT VaR 99.5%]", "[EVT ES 99%]",
            "[EVT Xi]", "[Hill Index]", "[EVT N Exceed]",
            "[EVT Xi Min]", "[EVT Xi Max]", "[EVT Xi Range]",
            "[EVT VaR99 Range]", "[EVT ES99 Range]",
            "[EVT Threshold Stable]", "[EVT Sensitivity Status]",
            "[EVT Interval Method]", "[EVT MCMC Acceptance]", "[EVT MCMC Samples]",
            "[EVT Xi P05]", "[EVT Xi P50]", "[EVT Xi P95]",
            "[EVT VaR99 P05]", "[EVT VaR99 P50]", "[EVT VaR99 P95]",
            "[EVT ES99 P05]", "[EVT ES99 P50]", "[EVT ES99 P95]",
        ]:
            full_prompt = full_prompt.replace(placeholder, "N/A (cần ≥ 756 phiên)")

    full_prompt += (
        "\n\n# V3 DIAGNOSTICS\n"
        f"- Methodology: {snap.get('methodology_version', 'N/A')}\n"
        f"- Tail regime: {snap.get('tail_regime', 'N/A')} ({snap.get('tail_risk_level', 'N/A')})\n"
        f"- Current log return: {snap.get('current_return', 0.0)*100:.2f}%\n"
        f"- VaR breach 95%: {int(bool(snap.get('var_breach_95', False)))}; "
        f"breach margin: {snap.get('breach_margin_95', 0.0)*100:.2f}pp\n"
        f"- Gaussian VaR99: {snap.get('gaussian_var_99', 0.0)*100:.2f}%; "
        f"EVT VaR99 gap: {snap.get('evt_gaussian_var99_gap', 0.0)*100:.2f}pp\n"
        f"- EVT threshold stable: {1 if snap.get('evt_sensitivity_stable') else 0}; "
        f"xi range: {snap.get('evt_sensitivity_xi_range', 0.0):.3f}\n"
        "- Method control: same-date VaR/ES uses prior-window returns only; no forward-fill; bad ticks abs(simple return)>50% removed.\n"
    )

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

    res = call_ai(client, sys_p, usr_p, model=model)
    footer_lines = [
        f"Methodology: {snap.get('methodology_version', 'N/A')}",
        f"Tail Regime: {snap.get('tail_regime', 'N/A')}",
        f"Tail Risk Level: {snap.get('tail_risk_level', 'N/A')}",
        f"Current Return: {snap.get('current_return', 0.0)*100:.2f}%",
        f"VaR Breach 95: {1 if snap.get('var_breach_95') else 0}",
        f"Breach Margin 95: {snap.get('breach_margin_95', 0.0)*100:.2f}pp",
        "EVT Method: POT_GPD_threshold_sensitivity_5_15pct_prior_window",
    ]
    if snap.get("evt_available"):
        footer_lines.extend(
            [
                f"EVT Xi MLE: {snap['evt_xi']:+.3f}",
                f"EVT Hill: {snap['hill_index']:+.3f}",
            ]
        )
    if snap.get("evt_sensitivity_available"):
        footer_lines.extend(
            [
                f"EVT Xi Min: {snap['evt_sensitivity_xi_min']:+.3f}",
                f"EVT Xi Max: {snap['evt_sensitivity_xi_max']:+.3f}",
                f"EVT Xi Range: {snap['evt_sensitivity_xi_range']:.3f}",
                f"EVT VaR99 Range: {abs(snap['evt_sensitivity_var99_range'])*100:.2f}pp",
                f"EVT ES99 Range: {abs(snap['evt_sensitivity_es99_range'])*100:.2f}pp",
                f"EVT Threshold Stable: {1 if snap.get('evt_sensitivity_stable') else 0}",
                f"EVT Sensitivity Status: {snap.get('evt_sensitivity_status', 'threshold_sensitive')}",
            ]
        )
    if snap.get("evt_interval_available"):
        footer_lines.extend(
            [
                f"EVT Interval Method: {snap.get('evt_interval_method', 'gpd_random_walk_mcmc')}",
                f"EVT MCMC Acceptance: {snap['evt_interval_acceptance_rate']:.1%}",
                f"EVT MCMC Samples: {snap.get('evt_interval_samples', 0)}",
                f"EVT Xi P05: {snap['evt_xi_p05']:+.3f}",
                f"EVT Xi P50: {snap['evt_xi_p50']:+.3f}",
                f"EVT Xi P95: {snap['evt_xi_p95']:+.3f}",
                f"EVT VaR99 P05: {snap['evt_var99_p05']*100:.2f}%",
                f"EVT VaR99 P50: {snap['evt_var99_p50']*100:.2f}%",
                f"EVT VaR99 P95: {snap['evt_var99_p95']*100:.2f}%",
                f"EVT ES99 P05: {snap['evt_es99_p05']*100:.2f}%",
                f"EVT ES99 P50: {snap['evt_es99_p50']*100:.2f}%",
                f"EVT ES99 P95: {snap['evt_es99_p95']*100:.2f}%",
            ]
        )
    res = _append_structured_footer(res, "var_cvar_vnindex_methodology", footer_lines)
    direct_metrics = {
        "historical_var_pct": snap.get("historical_var", 0.0) * 100.0,
        "expected_shortfall_pct": snap.get("expected_shortfall", 0.0) * 100.0,
        "tail_regime": snap.get("tail_regime"),
        "tail_risk_level": snap.get("tail_risk_level"),
        "var_breach_95": snap.get("var_breach_95"),
        "breach_margin_95_pp": snap.get("breach_margin_95", 0.0) * 100.0,
    }
    if snap.get("evt_available"):
        direct_metrics.update(
            {
                "evt_xi": snap.get("evt_xi"),
                "evt_var_99_pct": snap.get("evt_var_99", 0.0) * 100.0,
                "evt_es_99_pct": snap.get("evt_es_99", 0.0) * 100.0,
                "hill_index": snap.get("hill_index"),
            }
        )
    if snap.get("evt_sensitivity_available"):
        direct_metrics.update(
            {
                "evt_xi_min": snap.get("evt_sensitivity_xi_min"),
                "evt_xi_max": snap.get("evt_sensitivity_xi_max"),
                "evt_xi_range": snap.get("evt_sensitivity_xi_range"),
                "evt_var99_range_pp": abs(snap.get("evt_sensitivity_var99_range", 0.0)) * 100.0,
                "evt_es99_range_pp": abs(snap.get("evt_sensitivity_es99_range", 0.0)) * 100.0,
                "evt_threshold_stable": int(bool(snap.get("evt_sensitivity_stable"))),
            }
        )
    if snap.get("evt_interval_available"):
        direct_metrics.update(
            {
                "evt_xi_p05": snap.get("evt_xi_p05"),
                "evt_xi_p50": snap.get("evt_xi_p50"),
                "evt_xi_p95": snap.get("evt_xi_p95"),
            }
        )
    res = _append_direct_metrics(res, "var_cvar_vnindex", direct_metrics)
    _write_cache("var_cvar_vnindex", res, provider_key)
    return res

def _parse_date_from_filename(filename: str) -> date | None:
    """
    Trích xuất ngày từ tên file cache dạng ddmmyy hoặc ddmmyyyy ở cuối file.
    Trả về đối tượng datetime.date hoặc None nếu không khớp.
    """
    # 1. Tìm ddmmyy (6 chữ số) ở cuối tên file trước phần mở rộng
    # Ví dụ: fed_liquidity_kimi-2.6_280526.txt -> 280526
    match_6 = re.search(r'_(\d{6})$', filename)
    if match_6:
        d = match_6.group(1)
        try:
            return date(2000 + int(d[4:]), int(d[2:4]), int(d[:2]))
        except ValueError:
            pass
            
    # 2. Tìm ddmmyyyy (8 chữ số) ở cuối tên file
    # Ví dụ: 30052026
    match_8 = re.search(r'(\d{8})$', filename)
    if match_8:
        d = match_8.group(1)
        try:
            return date(int(d[4:]), int(d[2:4]), int(d[:2]))
        except ValueError:
            pass
            
    # 3. Quét bất kỳ chuỗi 6 hoặc 8 chữ số nào trong tên file
    match_any = re.findall(r'\d{6,8}', filename)
    for d in match_any:
        try:
            if len(d) == 6:
                return date(2000 + int(d[4:]), int(d[2:4]), int(d[:2]))
            elif len(d) == 8:
                return date(int(d[4:]), int(d[2:4]), int(d[:2]))
        except ValueError:
            continue
            
    return None


def _get_latest_report_for_macro(tool_id: str, provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """
    Quét tìm báo cáo AI gần nhất cho một công cụ vĩ mô.
    Trả về tuple: (ngày_báo_cáo, nội_dung_báo_cáo).
    Nếu không có, trả về ("N/A", "*Chưa có báo cáo phân tích*").
    """
    import datetime as datetime_mod
    cache_dir = DATA_LAKE / "daily_cache"
    
    if tool_id == "ltmm":
        cache_dir = DATA_LAKE / "data_LTMM" / "AI_CIO_raw"
        pattern = f"ltmm_analyst_{provider_key}_*.txt"
        fallback_pattern = "ltmm_analyst_*.txt"
    elif tool_id == "fed_liquidity":
        pattern = f"fed_liquidity_{provider_key}_*.txt"
        fallback_pattern = "fed_liquidity_*.txt"
    elif tool_id == "global_financial_conditions":
        pattern = f"global_financial_conditions_{provider_key}_*.txt"
        fallback_pattern = "global_financial_conditions_*.txt"
    elif tool_id == "vnibor":
        pattern = f"vnibor_{provider_key}_*.txt"
        fallback_pattern = "vnibor_*.txt"
    elif tool_id == "credit_spread":
        pattern = f"credit_spread_{provider_key}_*.txt"
        fallback_pattern = "credit_spread_*.txt"
    else:
        return "N/A", "*Không xác định được công cụ*"
        
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    files = list(cache_dir.glob(pattern))
    
    if not files and fallback_pattern:
        files = list(cache_dir.glob(fallback_pattern))
        
    if not files and tool_id == "ltmm":
        # Đối với LTMM quét thêm tất cả .txt/.md khác
        files = list(cache_dir.glob("*.txt")) + list(cache_dir.glob("*.md"))
        
    if not files:
        return "N/A", "*Chưa có báo cáo phân tích*"
        
    # Sắp xếp các file theo ngày thực tế được trích xuất (chronological order)
    # Nếu không trích xuất được ngày, dùng mtime làm tiêu chuẩn phụ
    def file_sort_key(p: Path):
        file_date = _parse_date_from_filename(p.stem)
        if file_date:
            return (file_date, p.stat().st_mtime)
        else:
            return (date(1970, 1, 1), p.stat().st_mtime)
            
    files = sorted(files, key=file_sort_key, reverse=True)
    for candidate_file in files:
        date_str = "N/A"
        parsed_date = _parse_date_from_filename(candidate_file.stem)
        if parsed_date:
            date_str = parsed_date.strftime('%d/%m/%Y')
        else:
            mtime = datetime_mod.datetime.fromtimestamp(candidate_file.stat().st_mtime)
            date_str = mtime.strftime('%d/%m/%Y')

        try:
            content = _read_cache_file(candidate_file, tool_id)
            if content is not None:
                return date_str, content.strip()
        except Exception as e:
            return "N/A", f"Lỗi đọc file: {e}"

    version = _cache_version_for_tool(tool_id)
    if version:
        return "N/A", f"*No current-methodology report found for cache version {version}*"
    return "N/A", "*Chưa có báo cáo phân tích*"


def _parse_report_date_label(date_label: str | None) -> date | None:
    raw = str(date_label or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d%m%Y", "%d%m%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


def _find_ltmm_source_json(date_label: str | None = None) -> Path | None:
    source_dir = DATA_LAKE / "data_LTMM" / "sourse_raw"
    parsed = _parse_report_date_label(date_label)
    if parsed:
        candidate = source_dir / f"{parsed.strftime('%d%m%Y')}.json"
        if candidate.exists():
            return candidate
    files = sorted(source_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _df_first_row(df: pd.DataFrame, column: str, value: str) -> pd.Series | None:
    if df.empty or column not in df.columns:
        return None
    rows = df.loc[df[column].astype(str).eq(value)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _series_float(row: pd.Series | None, key: str) -> float | None:
    if row is None or key not in row.index:
        return None
    try:
        value = row[key]
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _series_text(row: pd.Series | None, key: str, default: str = "N/A") -> str:
    if row is None or key not in row.index:
        return default
    value = row[key]
    if pd.isna(value):
        return default
    return str(value)


def _fmt_ltmm_number(value: Any, digits: int = 3) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):+.{digits}f}"
    except Exception:
        return "N/A"


def _format_ltmm_rows(df: pd.DataFrame, cols: list[str], limit: int = 8) -> str:
    if df.empty:
        return "N/A"
    keep = [col for col in cols if col in df.columns]
    if not keep:
        return "N/A"
    view = df[keep].head(limit).copy()
    for col in view.columns:
        if pd.api.types.is_numeric_dtype(view[col]):
            view[col] = view[col].map(lambda v: _fmt_ltmm_number(v) if pd.notna(v) else "N/A")
    return view.to_markdown(index=False)


def _build_ltmm_structured_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Build LTMM context that preserves FLI, FRI, MLI and trigger details for AI CIO."""
    report_date, raw_report = _get_latest_report_for_macro("ltmm", provider_key)
    source_path = _find_ltmm_source_json(report_date)
    if source_path is None:
        return report_date, raw_report

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        latest = pd.DataFrame(payload.get("latest_indices") or [])
        bottlenecks = pd.DataFrame(payload.get("bottlenecks") or [])
        overlays = pd.DataFrame(payload.get("overlays") or [])
        triggers = pd.DataFrame(payload.get("triggers") or [])
    except Exception as exc:
        return report_date, (
            f"DATA INSUFFICIENT: Could not parse LTMM source JSON ({exc}).\n\n"
            f"=== RAW LTMM ANALYST REPORT ===\n{raw_report}"
        )

    fli = _df_first_row(latest, "index_name", "FLI")
    mli = _df_first_row(latest, "index_name", "MLI")
    te = _df_first_row(latest, "index_name", "TE")
    fri_collateral = _df_first_row(latest, "index_name", "FRI_collateral")
    fli_value = _series_float(fli, "index_value")
    mli_value = _series_float(mli, "index_value")
    te_value = _series_float(te, "index_value")
    fri_collateral_value = _series_float(fri_collateral, "index_value")

    fire_triggers = pd.DataFrame()
    near_fire = pd.DataFrame()
    transmission_breakdown_fire = 0
    if not triggers.empty and "signal_state" in triggers.columns:
        fire_triggers = triggers.loc[triggers["signal_state"].astype(str).str.upper().eq("FIRE")].copy()
        if "trigger_id" in fire_triggers.columns:
            transmission_breakdown_fire = int(
                fire_triggers["trigger_id"].astype(str).eq("transmission_breakdown").any()
            )
        if {"fresh_conditions_met", "fresh_conditions_total"}.issubset(triggers.columns):
            near_fire = triggers.loc[
                ~triggers.index.isin(fire_triggers.index)
                & (pd.to_numeric(triggers["fresh_conditions_total"], errors="coerce") > 0)
                & (
                    pd.to_numeric(triggers["fresh_conditions_met"], errors="coerce")
                    >= pd.to_numeric(triggers["fresh_conditions_total"], errors="coerce") - 1
                )
            ].copy()

    top_bottlenecks = pd.DataFrame()
    if not bottlenecks.empty and "stress_score" in bottlenecks.columns:
        top_bottlenecks = bottlenecks.copy()
        top_bottlenecks["stress_score"] = pd.to_numeric(top_bottlenecks["stress_score"], errors="coerce")
        top_bottlenecks = top_bottlenecks.sort_values("stress_score", ascending=False)

    key_overlays = pd.DataFrame()
    if not overlays.empty and "overlay" in overlays.columns:
        overlay_names = {
            "FX offshore stress footprint",
            "Interbank line tightness proxy",
            "Equity-rate wedge",
            "VN30F basis pressure",
            "Fund system cash posture",
            "Foreign flow 5d pressure",
            "Margin call wave footprint",
        }
        key_overlays = overlays.loc[overlays["overlay"].astype(str).isin(overlay_names)].copy()
        if "stress_score" in key_overlays.columns:
            key_overlays["stress_score"] = pd.to_numeric(key_overlays["stress_score"], errors="coerce")
            key_overlays = key_overlays.sort_values("stress_score", ascending=False)

    parsed_source_date = _parse_report_date_label(source_path.stem)
    source_date_label = parsed_source_date.strftime("%d/%m/%Y") if parsed_source_date else source_path.stem
    date_label = report_date if report_date != "N/A" else source_date_label
    fli_state = _series_text(fli, "state")
    mli_state = _series_text(mli, "state")
    te_state = _series_text(te, "state")
    fri_state = _series_text(fri_collateral, "state")

    divergence = "N/A"
    if fli_value is not None and mli_value is not None:
        divergence = (
            f"FLI {fli_state} ({_fmt_ltmm_number(fli_value)}) -> "
            f"MLI {mli_state} ({_fmt_ltmm_number(mli_value)})"
        )
        if mli_value - fli_value >= 0.75:
            divergence += " | downstream materially tighter than upstream"
        elif abs(mli_value - fli_value) >= 0.5:
            divergence += " | meaningful transmission gap"
        else:
            divergence += " | no large upstream/downstream spread"

    snapshot = f"""
=== LTMM STRUCTURED SNAPSHOT - LIQUIDITY TRANSMISSION ===
- Report date: {date_label}
- Source JSON: {source_path.name}
- LTMM FLI: {_fmt_ltmm_number(fli_value)} | state: {fli_state} | quality: {_series_float(fli, 'quality_score')}
- LTMM MLI: {_fmt_ltmm_number(mli_value)} | state: {mli_state} | quality: {_series_float(mli, 'quality_score')}
- LTMM TE: {_fmt_ltmm_number(te_value)} | state: {te_state} | quality: {_series_float(te, 'quality_score')}
- LTMM FRI_collateral: {_fmt_ltmm_number(fri_collateral_value)} | state: {fri_state} | quality: {_series_text(fri_collateral, 'quality_state')}
- LTMM divergence: {divergence}
- LTMM Fire Trigger Count: {len(fire_triggers)}
- LTMM transmission_breakdown FIRE: {transmission_breakdown_fire}

Top bottlenecks by stress score:
{_format_ltmm_rows(top_bottlenecks, ['constraint', 'layer', 'stress_score', 'state', 'quality', 'observation_date'], limit=8)}

Key hard-gap / overlay footprints:
{_format_ltmm_rows(key_overlays, ['overlay', 'node', 'stress_score', 'state', 'quality_flag', 'observation_date'], limit=8)}

FIRE triggers:
{_format_ltmm_rows(fire_triggers, ['trigger_id', 'signal_state', 'fresh_conditions_met', 'fresh_conditions_total', 'conditions_excluded'], limit=8)}

Near-fire triggers:
{_format_ltmm_rows(near_fire, ['trigger_id', 'signal_state', 'fresh_conditions_met', 'fresh_conditions_total', 'conditions_excluded'], limit=8)}

Interpretation rule:
- Do not summarize LTMM as FLI alone. FLI is upstream funding supply.
- The AI CIO must jointly read FLI, MLI, TE, FRI bottlenecks, and FIRE/near-fire triggers.
- If FLI is neutral but MLI tightens or TE is breakdown, treat this as transmission blockage, not macro relief.
""".strip()

    if raw_report and not raw_report.startswith("*Ch"):
        snapshot += (
            "\n\n=== LTMM ANALYST REPORT - SUPPORTING PROSE ===\n"
            + _compact_text(raw_report, max_chars=2200)
        )
    snapshot = _append_direct_metrics(
        snapshot,
        "ltmm",
        {
            "ltmm_fli": fli_value,
            "ltmm_mli": mli_value,
            "ltmm_te": te_value,
            "ltmm_fri_collateral": fri_collateral_value,
            "ltmm_fire_trigger_count": len(fire_triggers),
            "ltmm_transmission_breakdown_fire": transmission_breakdown_fire,
            "fli_state": fli_state,
            "mli_state": mli_state,
            "te_state": te_state,
            "fri_collateral_state": fri_state,
        },
    )
    return date_label, snapshot


def _get_fed_liquidity_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Read the latest Fed Liquidity child AI report."""
    return _get_latest_report_for_macro("fed_liquidity", provider_key)


def run_fed_liquidity_child_report(
    client,
    provider_key: str = "kimi-2.6",
    model: str = None,
    force: bool = False,
) -> str:
    """
    Generate the Fed Liquidity child AI report from the latest data cache.

    Auto AI CIO is designed to consume child-tool txt reports. This function
    keeps that contract while ensuring the txt is regenerated from current data.
    """
    cached = None if force else _read_cache("fed_liquidity", provider_key)
    if cached:
        return cached

    try:
        from tools.fed_liquidity.quant.metrics import OUTPUT_COLUMNS, summarize_latest

        path = DATA_LAKE / "fed_liquidity_cache.csv"
        df_processed = pd.read_csv(path, parse_dates=["DATE"]).set_index("DATE").sort_index()
        numeric_cols = [c for c in OUTPUT_COLUMNS if c != "Signal"]
        for col in numeric_cols:
            if col in df_processed.columns:
                df_processed[col] = pd.to_numeric(df_processed[col], errors="coerce")
        summary = summarize_latest(df_processed)
    except Exception as e:
        result = f"DATA INSUFFICIENT: Không generate được Fed Liquidity child report ({e})"
        _write_cache("fed_liquidity", result, provider_key)
        return result

    prompt_path = ROOT_DIR / "promt" / "fed_liquidity_promt.md"
    prompt_template = prompt_path.read_text(encoding="utf-8")
    full_prompt = (
        prompt_template
        .replace("[Nhập ngày]", summary["date"])
        .replace("[Net Liquidity]", f"{summary['net_liquidity']:,.0f}")
        .replace("[WALCL]", f"{summary['walcl']:,.0f}")
        .replace("[WTREGEN]", f"{summary['wtregen']:,.0f}")
        .replace("[RRPONTSYD]", f"{summary['rrpontsyd']:,.0f}")
        .replace("[Impulse]", f"{summary['impulse']:+,.0f}")
        .replace("[Impulse_EMA]", f"{summary['impulse_ema']:+,.0f}")
        .replace("[Z_Score]", f"{summary['z_score']:+.2f}")
        .replace("[Signal]", summary["signal"])
    )

    parts = full_prompt.split("# INPUT DATA")
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["kimi-2.6"])
    result = call_ai(
        client,
        system_prompt,
        user_prompt,
        model=model or cfg["api_model"],
        temperature=cfg.get("temperature", AI_TEMPERATURE),
    )
    result = _append_direct_metrics(
        result,
        "fed_liquidity",
        {
            "fed_net_liquidity": summary.get("net_liquidity"),
            "fed_liquidity_impulse": summary.get("impulse"),
            "fed_liquidity_impulse_ema": summary.get("impulse_ema"),
            "fed_liquidity_zscore": summary.get("z_score"),
            "signal": summary.get("signal"),
            "walcl": summary.get("walcl"),
            "wtregen": summary.get("wtregen"),
            "rrpontsyd": summary.get("rrpontsyd"),
        },
    )
    _write_cache("fed_liquidity", result, provider_key)
    return result


def run_global_financial_conditions_child_report(
    client,
    provider_key: str = "kimi-2.6",
    model: str = None,
    force: bool = False,
) -> str:
    """
    Generate the Global FCI child AI report from the latest GFCM data cache.

    This is the missing step that caused Auto AI CIO to read a stale
    global_financial_conditions_*.txt even though the CSV cache was current.
    """
    cached = None if force else _read_cache("global_financial_conditions", provider_key)
    if cached:
        return cached

    try:
        from tools.global_financial_conditions.quant.metrics import (
            load_cached_gfcm,
            summarize_latest,
        )

        df_processed = load_cached_gfcm(DATA_LAKE / "global_financial_conditions_cache.csv")
        summary = summarize_latest(df_processed)
    except Exception as e:
        result = f"DATA INSUFFICIENT: Không generate được Global FCI child report ({e})"
        _write_cache("global_financial_conditions", result, provider_key)
        return result

    prompt_path = ROOT_DIR / "promt" / "global_financial_conditions_promt.md"
    prompt_template = prompt_path.read_text(encoding="utf-8")
    full_prompt = (
        prompt_template
        .replace("[Nhập ngày]", summary["date"])
        .replace("[VIX]", f"{summary['vix']:.2f}")
        .replace("[MOVE]", f"{summary['move']:.1f}")
        .replace("[SKEW]", f"{summary['skew']:.1f}")
        .replace("[OVX]", f"{summary['ovx']:.2f}")
        .replace("[VVIX]", f"{summary['vvix']:.1f}")
        .replace("[HY_OAS]", f"{summary['hy_oas']:.2f}")
        .replace("[CCC_OAS]", f"{summary['ccc_oas']:.2f}")
        .replace("[IG_OAS]", f"{summary['ig_oas']:.2f}")
        .replace("[EM_OAS]", f"{summary['em_oas']:.2f}")
        .replace("[CQS]", f"{summary['credit_quality_spread']:.2f}")
        .replace("[T10Y2Y]", f"{summary['t10y2y']:+.2f}")
        .replace("[DXY]", f"{summary['dxy']:.2f}")
        .replace("[VIX_pct]", f"{summary['vix_pct']*100:.0f}")
        .replace("[MOVE_pct]", f"{summary['move_pct']*100:.0f}")
        .replace("[SKEW_pct]", f"{summary['skew_pct']*100:.0f}")
        .replace("[OVX_pct]", f"{summary['ovx_pct']*100:.0f}")
        .replace("[VVIX_pct]", f"{summary['vvix_pct']*100:.0f}")
        .replace("[HY_pct]", f"{summary['hy_pct']*100:.0f}")
        .replace("[CCC_pct]", f"{summary['ccc_pct']*100:.0f}")
        .replace("[IG_pct]", f"{summary['ig_pct']*100:.0f}")
        .replace("[EM_pct]", f"{summary['em_pct']*100:.0f}")
        .replace("[T10Y2Y_pct]", f"{summary['t10y2y_pct']*100:.0f}")
        .replace("[DXY_pct]", f"{summary['dxy_pct']*100:.0f}")
        .replace("[CQS_pct]", f"{summary['cqs_pct']*100:.0f}")
        .replace("[VIX_z]", f"{summary['vix_z']:+.2f}")
        .replace("[MOVE_z]", f"{summary['move_z']:+.2f}")
        .replace("[SKEW_z]", f"{summary['skew_z']:+.2f}")
        .replace("[HY_z]", f"{summary['hy_z']:+.2f}")
        .replace("[CCC_z]", f"{summary['ccc_z']:+.2f}")
        .replace("[IG_z]", f"{summary['ig_z']:+.2f}")
        .replace("[PC1]", f"{summary['pc1_smooth']:+.2f}")
        .replace("[PC1_raw]", f"{summary['pc1']:+.2f}")
        .replace("[PC2]", f"{summary['pc2']:+.2f}")
        .replace("[PC1_pct]", f"{summary['pc1_pct']*100:.0f}")
        .replace("[PC1_5d]", f"{summary['pc1_5d_change']:+.2f}")
        .replace("[Regime]", summary["regime"])
        .replace("[Driver]", summary["driver"])
    )

    parts = full_prompt.split("# INPUT DATA")
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["kimi-2.6"])
    result = call_ai(
        client,
        system_prompt,
        user_prompt,
        model=model or cfg["api_model"],
        temperature=cfg.get("temperature", AI_TEMPERATURE),
    )
    result = _append_structured_footer(
        result,
        "global_financial_conditions_methodology",
        [
            f"CQS Percentile 3Y: {summary['cqs_pct']*100:.1f}",
            f"PC1 Regime Percentile 1Y: {summary['pc1_pct']*100:.1f}",
            "Indicator Percentile Window: 756 sessions max, 252 sessions min",
            "Z-Score Window: 252 sessions",
            "PCA Method: expanding_point_in_time",
            "PCA Full-History Fit: 0",
            "PCA Refit Every Sessions: 21",
        ],
    )
    result = _append_direct_metrics(
        result,
        "global_financial_conditions",
        {
            "cqs_percentile": summary.get("cqs_pct", 0.0) * 100.0,
            "gfcm_pc1_percentile": summary.get("pc1_pct", 0.0) * 100.0,
            "gfcm_pc1": summary.get("pc1"),
            "gfcm_ccc_oas": summary.get("ccc_oas"),
            "vix": summary.get("vix"),
            "move": summary.get("move"),
            "hy_oas": summary.get("hy_oas"),
            "regime": summary.get("regime"),
            "driver": summary.get("driver"),
        },
    )
    _write_cache("global_financial_conditions", result, provider_key)
    return result


def _get_gfcm_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Read the latest Global FCI child AI report."""
    return _get_latest_report_for_macro("global_financial_conditions", provider_key)


def run_credit_spread_child_report(
    client,
    provider_key: str = "kimi-2.6",
    model: str = None,
    force: bool = False,
) -> str:
    """Generate the canonical Credit Spread child report for AI CIO."""
    try:
        from tools.credit_spread.ai_analysis import is_report_current, load_canonical_snapshot, run_ai_analysis

        snapshot = load_canonical_snapshot()
        cached = None if force else _read_cache("credit_spread", provider_key)
        if cached and is_report_current(cached, snapshot["date"]):
            return cached
        result = run_ai_analysis(
            snapshot=snapshot,
            provider_key=provider_key,
            client=client,
            model=model,
        )
        result = _append_direct_metrics(
            result,
            "credit_spread",
            {
                "credit_spread_risk_premium_bps": snapshot.get("risk_premium_bps"),
                "credit_spread_change_bps": snapshot.get("risk_premium_change_bps"),
                "credit_spread_3p_change_bps": snapshot.get("risk_premium_change_3p_bps"),
                "credit_spread_percentile": snapshot.get("risk_premium_percentile"),
                "credit_spread_matched_periods": snapshot.get("matched_periods"),
                "credit_spread_bank_count": snapshot.get("bank_issuance_count"),
                "credit_spread_real_estate_count": snapshot.get("real_estate_issuance_count"),
                "direction": snapshot.get("direction"),
                "trend_3p": snapshot.get("trend_3p"),
                "data_quality": snapshot.get("data_quality"),
            },
        )
    except Exception as e:
        result = f"DATA INSUFFICIENT: Không generate được Credit Spread child report ({e})"

    _write_cache("credit_spread", result, provider_key)
    return result


def _get_credit_spread_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Combine canonical Credit Spread metrics with a current AI interpretation."""
    try:
        from tools.credit_spread.ai_analysis import build_structured_context, is_report_current, load_canonical_snapshot

        snapshot = load_canonical_snapshot()
        _, ai_report = _get_latest_report_for_macro("credit_spread", provider_key)
        has_current_report = (
            ai_report
            and not ai_report.startswith("*Chưa có")
            and not ai_report.startswith("*No current-methodology")
            and not ai_report.startswith("DATA INSUFFICIENT")
            and is_report_current(ai_report, snapshot["date"])
        )
        context = build_structured_context(snapshot, ai_report if has_current_report else None)
        if not has_current_report:
            context += "\n\nCredit Spread AI Cache: unavailable or stale; use canonical metrics above."
        return snapshot["date"], context
    except Exception as e:
        return "N/A", f"DATA INSUFFICIENT: Credit Spread structured context unavailable ({e})"


def _build_margin_m2_structured_snapshot() -> tuple[str, str]:
    """Build monthly US margin debt / M2 overlay context for AI CIO."""
    try:
        from tools.global_financial_conditions.quant.margin_m2 import (
            MARGIN_M2_CACHE,
            load_cached_margin_m2,
            summarize_latest_margin_m2,
        )

        df_margin_m2 = load_cached_margin_m2(MARGIN_M2_CACHE)
        summary = summarize_latest_margin_m2(df_margin_m2)
    except Exception as e:
        return "N/A", (
            "DATA INSUFFICIENT: Không build được US Margin Debt/M2 overlay "
            f"({e}). Đây là overlay monthly, không ảnh hưởng PCA Global FCI."
        )

    label = summary.get("date", "N/A")

    def fmt(key: str, suffix: str = "", decimals: int = 2) -> str:
        value = summary.get(key)
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):.{decimals}f}{suffix}"

    snapshot = f"""
=== US MARGIN DEBT / M2 STRUCTURED SNAPSHOT (OVERLAY ONLY) ===
- Date: {summary.get('date', 'N/A')}
- Margin debt: {fmt('margin_debt_million_usd', ' mn USD', 0)}
- M2: {fmt('m2_billion_usd', ' bn USD', 0)}
- Margin debt / M2: {fmt('margin_debt_pct_m2', '%')}
- Margin debt YoY: {fmt('margin_debt_yoy_pct', '%')}
- M2 YoY: {fmt('m2_yoy_pct', '%')}
- Margin/M2 5Y z-score: {fmt('margin_debt_pct_m2_zscore_5y', 'σ')}
- Margin/M2 10Y percentile: {fmt('margin_debt_pct_m2_percentile_10y', 'th', 0)}
- Signal regime: {summary.get('signal_regime', 'N/A')}
- FINRA source: {summary.get('finra_source_url', 'N/A')}
- FRED series: {summary.get('fred_series_id', 'N/A')}
- Cache updated at: {summary.get('last_updated_at', 'N/A')}

Usage discipline:
- Monthly/lagged speculative leverage overlay only.
- Not included in Global FCI PCA, PC1, PC1 percentile, or GFCM hard regime.
- Use it to interpret whether Global FCI stress is amplified by crowded leverage.
""".strip()
    snapshot = _append_direct_metrics(
        snapshot,
        "margin_m2_overlay",
        {
            "margin_debt_pct_m2": summary.get("margin_debt_pct_m2"),
            "margin_debt_yoy_pct": summary.get("margin_debt_yoy_pct"),
            "m2_yoy_pct": summary.get("m2_yoy_pct"),
            "margin_debt_pct_m2_zscore_5y": summary.get("margin_debt_pct_m2_zscore_5y"),
            "margin_debt_pct_m2_percentile_10y": summary.get("margin_debt_pct_m2_percentile_10y"),
            "signal_regime": summary.get("signal_regime"),
        },
    )
    return label, snapshot


def _build_vnibor_structured_trend() -> tuple[str, str]:
    """Build deterministic VNIBOR snapshot + 20-session trend for AI CIO macro layer."""
    try:
        from tools.vnibor.quant.metrics import (
            load_vnibor_data,
            process_vnibor_logic,
            summarize_latest,
            summarize_20d_trend,
        )

        df_processed = process_vnibor_logic(load_vnibor_data())
        summary = summarize_latest(df_processed)
        trend = summarize_20d_trend(df_processed, lookback=20)
    except Exception as e:
        return "N/A", f"DATA INSUFFICIENT: Không build được VNIBOR trend snapshot ({e})"

    label = summary.get("date", "N/A")
    snapshot = f"""
=== VNIBOR STRUCTURED SNAPSHOT + 20D TREND ===
Current snapshot:
- Date: {summary.get('date', 'N/A')}
- Overnight ON: {summary.get('overnight', 'N/A')}%
- 1 Week: {summary.get('w1', 'N/A')}%
- 2 Weeks: {summary.get('w2', 'N/A')}%
- ON Impulse: {summary.get('impulse', 'N/A')}%
- ON Z-Score: {summary.get('z_score', 'N/A')}
- ON Percentile: {summary.get('percentile', 'N/A')}
- Spread 1W-ON: {summary.get('spread_1w', 'N/A')}%
- Spread 2W-ON: {summary.get('spread_2w', 'N/A')}%
- Regime: {summary.get('regime', 'N/A')}
- Signal: {summary.get('signal', 'N/A')}

20-session trend:
- Trend label: {trend.get('trend_label', 'N/A')}
- ON 20D change: {trend.get('on_20d_change', 'N/A')}%
- ON MA5 20D change: {trend.get('on_ma5_20d_change', 'N/A')}%
- ON MA5 slope/session: {trend.get('on_ma5_slope', 'N/A')}%
- ON 20D avg/min/max: {trend.get('on_20d_avg', 'N/A')}% / {trend.get('on_20d_min', 'N/A')}% / {trend.get('on_20d_max', 'N/A')}%
- ON up/down days: {trend.get('up_days', 'N/A')} / {trend.get('down_days', 'N/A')}
- Inverted 1W-ON days: {trend.get('inversion_days', 'N/A')}
- STRESS/WARNING days: {trend.get('stress_warning_days', 'N/A')}
- Regime counts: {trend.get('regime_counts', 'N/A')}
- Signal counts: {trend.get('signal_counts', 'N/A')}
- 20D table:
{trend.get('trend_table', 'N/A')}
""".strip()
    snapshot = _append_direct_metrics(
        snapshot,
        "vnibor",
        {
            "vnibor_on": summary.get("overnight"),
            "vnibor_zscore": summary.get("z_score"),
            "vnibor_percentile": summary.get("percentile"),
            "vnibor_impulse": summary.get("impulse"),
            "vnibor_spread_1w": summary.get("spread_1w"),
            "vnibor_spread_2w": summary.get("spread_2w"),
            "vnibor_regime": summary.get("regime"),
            "vnibor_signal": summary.get("signal"),
            "vnibor_stress_warning_days_20d": trend.get("stress_warning_days"),
            "vnibor_trend_label": trend.get("trend_label"),
        },
    )
    return label, snapshot


def _build_vnibor_child_prompt(summary: dict, trend: dict) -> str:
    prompt_path = ROOT_DIR / "promt" / "vnibor_promt.md"
    prompt_template = prompt_path.read_text(encoding="utf-8")
    return (
        prompt_template
        .replace("[Nhập ngày]", summary.get("date", "N/A"))
        .replace("[Overnight_ON]", f"{summary.get('overnight', 0.0):.2f}")
        .replace("[1_Week]", f"{summary.get('w1', 0.0):.2f}")
        .replace("[2_Weeks]", f"{summary.get('w2', 0.0):.2f}")
        .replace("[ON_Impulse]", f"{summary.get('impulse', 0.0):+.2f}")
        .replace("[ON_ZScore]", f"{summary.get('z_score', 0.0):+.2f}")
        .replace("[ON_Percentile]", f"{summary.get('percentile', 0.0):.3f}")
        .replace("[Spread_1W_ON]", f"{summary.get('spread_1w', 0.0):+.2f}")
        .replace("[Spread_2W_ON]", f"{summary.get('spread_2w', 0.0):+.2f}")
        .replace("[Regime]", summary.get("regime", "N/A"))
        .replace("[Signal]", summary.get("signal", "N/A"))
        .replace("[Trend_20D_Label]", trend.get("trend_label", "N/A"))
        .replace("[ON_20D_Change]", trend.get("on_20d_change", "N/A"))
        .replace("[ON_MA5_20D_Change]", trend.get("on_ma5_20d_change", "N/A"))
        .replace("[ON_MA5_20D_Slope]", trend.get("on_ma5_slope", "N/A"))
        .replace("[ON_20D_Avg]", trend.get("on_20d_avg", "N/A"))
        .replace("[ON_20D_Min]", trend.get("on_20d_min", "N/A"))
        .replace("[ON_20D_Max]", trend.get("on_20d_max", "N/A"))
        .replace("[ON_20D_Up_Days]", trend.get("up_days", "N/A"))
        .replace("[ON_20D_Down_Days]", trend.get("down_days", "N/A"))
        .replace("[Inversion_20D_Count]", trend.get("inversion_days", "N/A"))
        .replace("[Stress_Warning_20D_Count]", trend.get("stress_warning_days", "N/A"))
        .replace("[Regime_20D_Counts]", trend.get("regime_counts", "N/A"))
        .replace("[Signal_20D_Counts]", trend.get("signal_counts", "N/A"))
        .replace("[Trend_20D_Table]", trend.get("trend_table", "N/A"))
    )


def run_vnibor_child_report(
    client,
    provider_key: str = "kimi-2.6",
    model: str = None,
    force: bool = False,
) -> str:
    """
    Generate the VNIBOR child AI report from the latest VNIBOR data.

    Auto AI CIO consumes child-tool txt reports. Without this step, it can read
    the last manually generated VNIBOR cache even when the CSV data is current.
    """
    cached = None if force else _read_cache("vnibor", provider_key)
    if cached:
        return cached

    try:
        from tools.vnibor.quant.metrics import (
            load_vnibor_data,
            process_vnibor_logic,
            summarize_latest,
            summarize_20d_trend,
        )

        df_processed = process_vnibor_logic(load_vnibor_data())
        summary = summarize_latest(df_processed)
        trend = summarize_20d_trend(df_processed, lookback=20)
        full_prompt = _build_vnibor_child_prompt(summary, trend)
    except Exception as e:
        result = f"DATA INSUFFICIENT: Không generate được VNIBOR child report ({e})"
        _write_cache("vnibor", result, provider_key)
        return result

    parts = full_prompt.split("# INPUT DATA")
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["kimi-2.6"])
    result = call_ai(
        client,
        system_prompt,
        user_prompt,
        model=model or cfg["api_model"],
        temperature=cfg.get("temperature", AI_TEMPERATURE),
    )
    result = _append_direct_metrics(
        result,
        "vnibor",
        {
            "vnibor_on": summary.get("overnight"),
            "vnibor_zscore": summary.get("z_score"),
            "vnibor_percentile": summary.get("percentile"),
            "vnibor_impulse": summary.get("impulse"),
            "vnibor_spread_1w": summary.get("spread_1w"),
            "vnibor_spread_2w": summary.get("spread_2w"),
            "vnibor_regime": summary.get("regime"),
            "vnibor_signal": summary.get("signal"),
            "vnibor_stress_warning_days_20d": trend.get("stress_warning_days"),
        },
    )
    _write_cache("vnibor", result, provider_key)
    return result


def _get_vnibor_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Combine structured VNIBOR trend with optional cached VNIBOR AI report."""
    snapshot_date, snapshot = _build_vnibor_structured_trend()
    ai_date, ai_report = _get_latest_report_for_macro("vnibor", provider_key)
    snapshot_dt = _parse_report_date_label(snapshot_date)
    ai_dt = _parse_report_date_label(ai_date)
    is_stale = snapshot_dt is not None and ai_dt is not None and ai_dt < snapshot_dt
    has_current_ai_report = (
        ai_report
        and not ai_report.startswith("*Chưa có")
        and not ai_report.startswith("*No current-methodology")
        and not is_stale
    )
    if has_current_ai_report:
        context = (
            f"{snapshot}\n\n"
            f"=== VNIBOR AI INTERPRETATION CACHE (Ngày báo cáo: {ai_date}) ===\n"
            f"{ai_report}"
        )
    else:
        cache_note = "*Chưa có cache AI riêng của VNIBOR; AI CIO phải tự diễn giải từ structured snapshot + 20D trend phía trên.*"
        if is_stale:
            cache_note = (
                f"*Bỏ qua cache AI VNIBOR ngày {ai_date} vì cũ hơn snapshot dữ liệu {snapshot_date}; "
                "AI CIO phải tự diễn giải từ structured snapshot + 20D trend phía trên.*"
            )
        elif ai_report and ai_report.startswith("*No current-methodology"):
            cache_note = (
                f"{ai_report}\n"
                "*AI CIO phải tự diễn giải từ structured snapshot + 20D trend phía trên.*"
            )
        context = (
            f"{snapshot}\n\n"
            "=== VNIBOR AI INTERPRETATION CACHE ===\n"
            f"{cache_note}"
        )
    return snapshot_date, context


def _get_latest_vn100_ai_report(provider_key: str = "kimi-2.6", mode_key: str = "yoy") -> tuple[str, str]:
    """Return latest current-methodology VN100 AI interpretation for this provider/mode."""
    import datetime as datetime_mod

    cache_dir = DATA_LAKE / "daily_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mode_key = str(mode_key or "yoy").lower()
    files = list(cache_dir.glob(f"vn100_earnings_health_{provider_key}_{mode_key}_*.txt"))
    if not files:
        files = list(cache_dir.glob(f"vn100_earnings_health_*_{mode_key}_*.txt"))
    if not files:
        return "N/A", ""

    def file_sort_key(p: Path):
        file_date = _parse_date_from_filename(p.stem)
        if file_date:
            return (file_date, p.stat().st_mtime)
        return (date(1970, 1, 1), p.stat().st_mtime)

    for latest_file in sorted(files, key=file_sort_key, reverse=True):
        parsed_date = _parse_date_from_filename(latest_file.stem)
        if parsed_date:
            date_str = parsed_date.strftime("%d/%m/%Y")
        else:
            mtime = datetime_mod.datetime.fromtimestamp(latest_file.stat().st_mtime)
            date_str = mtime.strftime("%d/%m/%Y")

        try:
            content = _read_cache_file(latest_file, "vn100_earnings_health")
            if content is not None:
                return date_str, content.strip()
        except Exception as e:
            return "N/A", f"Lỗi đọc file VN100 AI cache: {e}"

    return "N/A", ""


def _build_vn100_structured_snapshot() -> tuple[str, str]:
    """Build deterministic VN100 context so AI CIO can use the tool even without VN100 AI cache."""
    try:
        from tools.vn100_earnings_health.quant.ai_analysis import prepare_ai_payload
        from tools.vn100_earnings_health.quant.config import OUTPUT_DIR
        from tools.vn100_earnings_health.quant.pipeline import run_and_write

        if not (OUTPUT_DIR / "company_scores.parquet").exists():
            run_and_write()
        outputs = {
            "company": pd.read_parquet(OUTPUT_DIR / "company_scores.parquet"),
            "sector": pd.read_parquet(OUTPUT_DIR / "sector_scores.parquet"),
            "vn100": pd.read_parquet(OUTPUT_DIR / "vn100_scores.parquet"),
            "core_matrix": pd.read_parquet(OUTPUT_DIR / "core_consistency_matrix.parquet"),
            "transmission": pd.read_parquet(OUTPUT_DIR / "transmission_matrix.parquet"),
            "pca": pd.read_parquet(OUTPUT_DIR / "pca_factor.parquet"),
            "pca_loadings": pd.read_parquet(OUTPUT_DIR / "pca_loadings.parquet"),
            "alerts": pd.read_parquet(OUTPUT_DIR / "alerts.parquet"),
            "metadata": pd.read_parquet(OUTPUT_DIR / "ticker_metadata.parquet"),
        }
        payload = prepare_ai_payload(outputs, mode="YoY")
    except Exception as e:
        return "N/A", f"DATA INSUFFICIENT: Không build được VN100 Corporate Health snapshot ({e})"

    universe_count = "N/A"
    try:
        universe_count = str(int(outputs["metadata"]["ticker"].nunique()))
    except Exception:
        pass

    label = f"{payload.get('period', 'N/A')} / YoY"
    snapshot = f"""
=== VN100 CORPORATE HEALTH STRUCTURED SNAPSHOT ===
- Mode: {payload.get('mode', 'YoY')}
- Period: {payload.get('period', 'N/A')}
- Valid company count: {payload.get('valid_company_count', 'N/A')} / {universe_count}
- VN100 Health Score: {payload.get('vn100_health_score', 'N/A')}
- Market-cap weighted Health Score: {payload.get('vn100_health_score_market_cap_weighted', 'N/A')}
- Market-cap Health Gap: {payload.get('market_cap_health_gap', 'N/A')}
- Regime: {payload.get('regime', 'N/A')}

Rule-based verdict anchor:
- Verdict: {payload.get('final_verdict', 'N/A')}
- Macro Read: {payload.get('final_macro_read', 'N/A')}
- Confidence: {payload.get('final_confidence', 'N/A')}
- Analytical Stance: {payload.get('final_stance', 'N/A')}
- Accounting Recovery: {payload.get('accounting_recovery_read', 'N/A')}
- Cash-confirmed Recovery: {payload.get('cash_confirmed_recovery_read', 'N/A')}
- Sector Diffusion: {payload.get('sector_diffusion_read', 'N/A')}
- Systemic Stress: {payload.get('systemic_stress_read', 'N/A')}

Breadth and stress:
- Revenue Breadth: {payload.get('revenue_breadth', 'N/A')}
- Profit Breadth: {payload.get('profit_breadth', 'N/A')}
- CFO Breadth: {payload.get('cfo_breadth', 'N/A')}
- Healthy Growth Breadth: {payload.get('healthy_growth_breadth', 'N/A')}
- Working Capital Stress Index: {payload.get('working_capital_stress_index', 'N/A')}
- Leverage Stress Index: {payload.get('leverage_stress_index', 'N/A')}
- Sector Diffusion Score: {payload.get('sector_diffusion_score', 'N/A')}
- Positive Sector Count: {payload.get('positive_sector_count', 'N/A')} / {payload.get('valid_sector_count', 'N/A')}

Sector leadership and big-cap check:
- Sector Leadership: {payload.get('sector_leadership_read', 'N/A')}
- Big-cap Read: {payload.get('big_cap_read', 'N/A')}
- Top-sector Market-cap Share: {payload.get('top_sector_market_cap_share', 'N/A')}
- Positive-sector Market-cap Share: {payload.get('positive_sector_market_cap_share', 'N/A')}

Evidence:
{payload.get('final_evidence', 'N/A')}

Built-in diagnosis:
{payload.get('main_diagnosis', 'N/A')}

VN100 trend:
{payload.get('vn100_trend_table', 'N/A')}

Sector scores:
{payload.get('sector_table', 'N/A')}

Top companies:
{payload.get('top_company_table', 'N/A')}

Bottom companies:
{payload.get('bottom_company_table', 'N/A')}

Improving companies:
{payload.get('improving_company_table', 'N/A')}

Deteriorating companies:
{payload.get('deteriorating_company_table', 'N/A')}

Matrix diagnostics:
{payload.get('matrix_diagnostics_table', 'N/A')}

Transmission weak/broken links:
{payload.get('transmission_breakdown_table', 'N/A')}

Alerts:
{payload.get('alerts_table', 'N/A')}

PCA validation:
- PCA common health factor: {payload.get('pca_common_health_factor', 'N/A')}
- PCA explained variance: {payload.get('pca_explained_variance', 'N/A')}

Watch next:
{payload.get('watch_next', 'N/A')}
""".strip()
    snapshot = _append_direct_metrics(
        snapshot,
        "vn100_corporate_health",
        {
            "vn100_health_score": payload.get("vn100_health_score"),
            "vn100_health_score_market_cap_weighted": payload.get("vn100_health_score_market_cap_weighted"),
            "valid_company_count": payload.get("valid_company_count"),
            "regime": payload.get("regime"),
            "revenue_breadth": payload.get("revenue_breadth"),
            "profit_breadth": payload.get("profit_breadth"),
            "cfo_breadth": payload.get("cfo_breadth"),
            "healthy_growth_breadth": payload.get("healthy_growth_breadth"),
            "working_capital_stress_index": payload.get("working_capital_stress_index"),
            "leverage_stress_index": payload.get("leverage_stress_index"),
            "sector_diffusion_score": payload.get("sector_diffusion_score"),
            "positive_sector_count": payload.get("positive_sector_count"),
            "valid_sector_count": payload.get("valid_sector_count"),
        },
    )
    return label, snapshot


def _get_vn100_corporate_health_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Combine current structured VN100 data with optional cached AI interpretation."""
    snapshot_label, snapshot = _build_vn100_structured_snapshot()
    ai_date, ai_report = _get_latest_vn100_ai_report(provider_key)
    if ai_report:
        context = (
            f"{snapshot}\n\n"
            f"=== VN100 AI INTERPRETATION CACHE (Ngày báo cáo: {ai_date}) ===\n"
            f"{ai_report}"
        )
    else:
        context = (
            f"{snapshot}\n\n"
            "=== VN100 AI INTERPRETATION CACHE ===\n"
            "*Chưa có cache AI riêng của VN100; AI CIO phải tự diễn giải từ structured snapshot phía trên.*"
        )
    return snapshot_label, context


def _get_vn100_earnings_health_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Backward-compatible alias for the VN100 Corporate Health context."""
    return _get_vn100_corporate_health_context(provider_key)


def _build_abm_structured_snapshot() -> tuple[str, str]:
    """Build deterministic ABM stress snapshot for AI CIO tail-risk evidence."""
    try:
        paths = {
            "state": DATA_LAKE / "abm_behavioral_state.csv",
            "stress": DATA_LAKE / "abm_stress_test.csv",
            "alert": DATA_LAKE / "abm_alert.csv",
            "latent": DATA_LAKE / "abm_latent_state.csv",
            "validation": DATA_LAKE / "abm_validation.csv",
        }
        required = ("state", "stress", "alert")
        missing = [name for name in required if not paths[name].exists()]
        if missing:
            missing_files = ", ".join(paths[name].name for name in missing)
            return "N/A", f"DATA INSUFFICIENT: Missing ABM files: {missing_files}"

        state_df = pd.read_csv(paths["state"])
        stress_df = pd.read_csv(paths["stress"])
        alert_df = pd.read_csv(paths["alert"])
        if state_df.empty or stress_df.empty or alert_df.empty:
            return "N/A", "DATA INSUFFICIENT: ABM files are empty"

        latest_state = state_df.iloc[-1].to_dict()
        latest_stress = stress_df.iloc[-1].to_dict()
        latest_alert = alert_df.iloc[-1].to_dict()
        latest_latent: dict[str, Any] = {}
        latest_validation: dict[str, Any] = {}
        if paths["latent"].exists():
            latent_df = pd.read_csv(paths["latent"])
            if not latent_df.empty:
                latest_latent = latent_df.iloc[-1].to_dict()
        if paths["validation"].exists():
            validation_df = pd.read_csv(paths["validation"])
            if not validation_df.empty:
                latest_validation = validation_df.iloc[-1].to_dict()

        as_of_date = str(latest_alert.get("as_of_date") or latest_state.get("as_of_date") or "N/A")
    except Exception as e:
        return "N/A", f"DATA INSUFFICIENT: Error reading ABM data ({e})"

    def pct(value: Any, digits: int = 2) -> str:
        try:
            if value is None or pd.isna(value):
                return "N/A"
            return f"{float(value) * 100.0:.{digits}f}%"
        except Exception:
            return "N/A"

    def num(value: Any, digits: int = 2) -> str:
        try:
            if value is None or pd.isna(value):
                return "N/A"
            return f"{float(value):.{digits}f}"
        except Exception:
            return "N/A"

    def raw_num(value: Any, digits: int = 1) -> str:
        try:
            if value is None or pd.isna(value):
                return "N/A"
            return f"{float(value):.{digits}f}"
        except Exception:
            return "N/A"

    def bool_label(value: Any) -> str:
        if isinstance(value, str):
            return "Yes" if value.strip().lower() in {"1", "true", "yes", "y"} else "No"
        try:
            if value is None or pd.isna(value):
                return "N/A"
        except Exception:
            pass
        return "Yes" if bool(value) else "No"

    def warning_drivers(value: Any) -> str:
        if value is None:
            return "N/A"
        text = str(value).strip()
        if not text:
            return "N/A"
        parts = [part.strip().replace("_", " ").capitalize() for part in text.split(",") if part.strip()]
        return "; ".join(parts) if parts else "N/A"

    early_score = latest_alert.get("early_warning_score")
    early_level = latest_alert.get("early_warning_level", "N/A")
    warning_basis = latest_alert.get("warning_basis", "N/A")
    panel_used = latest_alert.get("alert_uses_quant_platform_panel", latest_state.get("qp_panel_available"))

    snapshot = f"""
=== ABM V4 EARLY-WARNING & MARGIN CASCADE STRESS MONITOR ===
Current snapshot:
- Date: {as_of_date}
- Regime Flag: {latest_alert.get('regime_flag', 'N/A')}
- Early-warning Score: {raw_num(early_score)}/100
- Early-warning Level: {early_level}
- Early-warning Drivers: {warning_drivers(warning_basis)}
- Uses Quant Platform stock panel: {bool_label(panel_used)}
- Distance to Cascade: {pct(latest_alert.get('distance_to_cascade'))}
- Simulated Panic Ratio: {pct(latest_stress.get('panic_ratio'))}
- Exogenous Drawdown: {pct(latest_stress.get('dd_exogenous'))}
- Endogenous Drawdown: {pct(latest_stress.get('dd_endogenous'))}
- Total Drawdown under shock: {pct(latest_stress.get('dd_total'))}
- Margin Call Events: {latest_stress.get('margin_call_events', latest_stress.get('margin_calls', 'N/A'))}
- Simulation Runs: {latest_stress.get('simulation_runs', 'N/A')}
- Stress Confidence: {pct(latest_alert.get('stress_confidence', latest_stress.get('stress_confidence')))}
- Input Quality Score: {pct(latest_alert.get('input_quality_score', latest_state.get('input_quality_score')))}
- Methodology Version: {latest_alert.get('methodology_version', 'N/A')}

Agent population and leverage:
- Fundamental Investors: {pct(latest_state.get('pct_fundamental'))}
- Momentum Traders: {pct(latest_state.get('pct_momentum'))}
- Foreign Institutional: {pct(latest_state.get('pct_foreign'))}
- Leveraged Speculators: {pct(latest_state.get('pct_leveraged'))}
- Noise Traders: {pct(latest_state.get('pct_noise'))}
- Avg Leverage Ratio: {num(latest_state.get('avg_leverage_ratio'))}x

Latent margin state:
- Market Liquidity Index (MLI): {num(latest_state.get('mli'))}
- Liquidity Stress: {num(latest_state.get('liquidity_stress'))}
- Valuation Gap: {pct(latest_state.get('valuation_gap'))}
- Trend Z-score: {num(latest_state.get('trend_z'))}
- Breadth Z-score: {num(latest_state.get('breadth_z'))}
- Foreign Flow Z-score: {num(latest_state.get('foreign_flow_z'))}
- Margin Pressure Z-score: {num(latest_state.get('margin_pressure_z'))}
- Margin Leverage Level: {num(latest_state.get('margin_leverage_level', latest_latent.get('margin_leverage_level')))}
- Margin Call Trigger Pressure: {num(latest_state.get('margin_call_trigger_pressure', latest_latent.get('margin_call_trigger_pressure')))}
- Cascade Vulnerability: {num(latest_state.get('cascade_vulnerability', latest_latent.get('cascade_vulnerability')))}
- Latent Confidence Score: {num(latest_state.get('latent_confidence_score', latest_latent.get('latent_confidence_score')))}
- Validation Status: {latest_latent.get('validation_status', latest_validation.get('validation_status', 'N/A'))}
- Validation Quality: {pct(latest_state.get('validation_quality', latest_latent.get('validation_quality')))}
- Validation AUC: {num(latest_validation.get('auc'))}
- Top Decile Event Lift: {num(latest_validation.get('lift_top_decile'))}

Usage discipline:
- ABM v4 is a pre-shock early-warning dashboard for leverage/crowding stress and forced-selling amplification.
- Treat Early-warning Score/Level as the primary ABM signal; distance to cascade, panic ratio, leverage, and vulnerability are supporting diagnostics.
- YELLOW means risk-budget caution, ORANGE means de-risking pressure, RED means severe cascade-risk warning.
- Do not interpret ABM as exact crash timing or as a standalone directional price forecast.
""".strip()
    try:
        from tools.abm_simulator.report import snapshot as abm_snapshot

        direct = abm_snapshot()
    except Exception:
        direct = {}
    if direct:
        snapshot = _append_direct_metrics(
            snapshot,
            "abm_simulator",
            {
                "abm_early_warning_score": direct.get("early_warning_score"),
                "early_warning_level": direct.get("early_warning_level"),
                "distance_to_cascade_pct": direct.get("distance_to_cascade_pct"),
                "panic_ratio_pct": direct.get("panic_ratio_pct"),
                "abm_avg_leverage_ratio": direct.get("avg_leverage_ratio"),
                "cascade_vulnerability": direct.get("cascade_vulnerability"),
                "abm_stress_confidence_pct": direct.get("stress_confidence_pct"),
                "input_quality_score_pct": direct.get("input_quality_score_pct"),
                "regime_flag": direct.get("regime_flag"),
                "methodology_version": direct.get("methodology_version"),
            },
        )
    return as_of_date, snapshot


def _empty_consensus_buckets() -> dict[str, list[dict[str, Any]]]:
    return {"bullish": [], "bearish": [], "neutral_or_mixed": []}


def _build_consensus_map(current_packets: list[dict[str, Any]], tool_scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate deterministic adapter consensus from provider-dependent prose interpretation."""
    hard = _empty_consensus_buckets()
    soft = _empty_consensus_buckets()
    scored_tools = {str(item.get("tool") or "") for item in tool_scores}

    for item in tool_scores:
        bias = item.get("tool_bias") if item.get("tool_bias") in hard else "neutral_or_mixed"
        hard[bias].append(
            {
                "tool": item.get("tool"),
                "tool_score": item.get("tool_score"),
                "tool_regime": item.get("tool_regime"),
                "reason": item.get("score_reason"),
            }
        )

    for packet in current_packets:
        tool = str(packet.get("tool") or "")
        if tool in scored_tools or packet.get("consensus_eligible") is False:
            continue
        bias = packet.get("bias") if packet.get("bias") in soft else "neutral_or_mixed"
        soft[bias].append(
            {
                "tool": tool,
                "source": "excerpt_inference",
                "confidence": "soft",
                "score": packet.get("score"),
                "regime": packet.get("regime"),
            }
        )

    return {
        "hard_adapter_consensus": hard,
        "soft_interpretive_consensus": soft,
        "usage_rule": (
            "Report hard_adapter_consensus as the stable cross-model consensus. "
            "Report soft_interpretive_consensus separately as provider-dependent interpretation; "
            "do not mix soft bullish/no-action labels into hard consensus counts."
        ),
    }


def _build_decision_state(
    evidence_packets: list[dict[str, Any]],
    history_ledger: list[dict[str, Any]],
    report_date: str,
    data_date: str,
) -> dict[str, Any]:
    """Build a compact deterministic state so the final LLM explains decisions instead of re-reading prose."""
    current_packets = [packet for packet in evidence_packets if packet.get("layer") != "history"]
    scoring_packets = [packet for packet in current_packets if _is_scoring_evidence_packet(packet)]
    bias_counts = {
        "bullish": sum(1 for packet in scoring_packets if packet.get("bias") == "bullish"),
        "bearish": sum(1 for packet in scoring_packets if packet.get("bias") == "bearish"),
        "neutral_or_mixed": sum(1 for packet in scoring_packets if packet.get("bias") == "neutral_or_mixed"),
    }
    hard_constraints: list[str] = []
    metric_values: dict[str, Any] = {}
    tool_scores: list[dict[str, Any]] = []
    for packet in scoring_packets:
        adapter_score = packet.get("adapter_score")
        if not isinstance(adapter_score, dict):
            adapter_score = score_tool_packet(str(packet.get("tool") or ""), packet.get("key_metrics") or {})
        if isinstance(adapter_score, dict):
            tool_scores.append({"tool": packet.get("tool"), **adapter_score})
        for key, value in (packet.get("key_metrics") or {}).items():
            metric_values[f"{packet.get('tool')}.{key}"] = value
            if key == "ssi_pct" and value >= 70:
                hard_constraints.append(f"ESR SSI elevated at {value:.1f}%")
            if key == "breadth_ma20_pct" and value < 45:
                hard_constraints.append(f"Breadth MA20 weak at {value:.1f}%")
            if key == "cqs_percentile" and value >= 80:
                hard_constraints.append(f"Global FCI CQS high at {value:.1f}")
            if key == "pvgo_pct" and value >= 50:
                hard_constraints.append(f"PVGO expectation risk high at {value:.1f}%")
            if key == "abm_early_warning_score" and value >= 75:
                hard_constraints.append(f"ABM early-warning RED at {value:.1f}/100")
            elif key == "abm_early_warning_score" and value >= 60:
                hard_constraints.append(f"ABM early-warning ORANGE at {value:.1f}/100")

    evt_xi = _safe_float(metric_values.get("var_cvar_vnindex.evt_xi"))
    evt_xi_min = _safe_float(metric_values.get("var_cvar_vnindex.evt_xi_min"))
    evt_xi_range = _safe_float(metric_values.get("var_cvar_vnindex.evt_xi_range"))
    if evt_xi is not None:
        if evt_xi_min is None:
            if evt_xi >= 0.25:
                hard_constraints.append(f"EVT xi elevated at {evt_xi:.3f} (legacy single-threshold)")
        elif evt_xi >= 0.30 and evt_xi_min >= 0.30:
            hard_constraints.append(f"EVT fat-tail robust across thresholds: xi={evt_xi:.3f}, xi_min={evt_xi_min:.3f}")
        elif evt_xi >= 0.25 and evt_xi_min >= 0.25:
            hard_constraints.append(f"EVT elevated tail robust across thresholds: xi={evt_xi:.3f}, xi_min={evt_xi_min:.3f}")
        elif evt_xi >= 0.30:
            suffix = f", xi_range={evt_xi_range:.3f}" if evt_xi_range is not None else ""
            hard_constraints.append(
                f"EVT xi threshold-sensitive: base xi={evt_xi:.3f}, xi_min={evt_xi_min:.3f}{suffix}; no standalone hard cap"
            )

    consensus_map = _build_consensus_map(current_packets, tool_scores)
    metric_implied = derive_metric_implied_scores(metric_values, bias_counts, tool_scores=tool_scores)
    previous = history_ledger[0] if history_ledger else {}
    score_delta = None
    try:
        if previous.get("score") not in (None, "N/A", ""):
            score_delta = round(float(metric_implied["metric_implied_score"]) - float(previous["score"]), 1)
    except Exception:
        score_delta = None

    return {
        "report_date": report_date,
        "data_date": data_date,
        "bias_counts": bias_counts,
        "consensus_map": consensus_map,
        "hard_constraints": sorted(set(hard_constraints)),
        "metric_values": metric_values,
        "tool_scores": tool_scores,
        "metric_implied_subscores": {
            "macro_risk_score": metric_implied["macro_risk_score"],
            "market_internal_score": metric_implied["market_internal_score"],
            "tail_risk_score": metric_implied["tail_risk_score"],
        },
        "metric_implied_score": metric_implied["metric_implied_score"],
        "metric_implied_regime": metric_implied["metric_implied_regime"],
        "tool_score_count": metric_implied.get("tool_score_count", len(tool_scores)),
        "score_band_reason": metric_implied["score_band_reason"],
        "previous_cio_diagnostic": {
            "date": previous.get("date"),
            "regime": previous.get("regime"),
            "score_delta_from_metric_implied": score_delta,
            "use_rule": "Diagnostic only. Do not anchor final score to prior CIO score.",
        } if previous else None,
        "writer_rules": [
            "Do not copy historical prose; use history only for deltas.",
            "Use evidence packets as the source of truth; omit raw child-report narration.",
            "In Tool Consensus, separate hard_adapter_consensus from soft_interpretive_consensus.",
            "Use metric_implied_score/regime as the baseline score before any LLM overlay.",
            "Do not place final score in 0-14 solely because recent history was 11-13.",
            "Hard constraints dominate LLM overlay and allocation.",
            "If evidence is missing, mark it DATA INSUFFICIENT instead of filling gaps.",
        ],
    }


def _build_ai_cio_structured_context(
    data_note: str,
    historical_block: str,
    evidence_packets: list[dict[str, Any]],
    decision_state: dict[str, Any],
    metrics_snapshot: dict[str, Any] | None = None,
) -> str:
    sections = [
        f"=== REPORT METADATA ===\n{data_note}",
        _format_json_context(
            "DAILY METRICS SNAPSHOT - AUTHORITATIVE STRUCTURED INPUT",
            _compact_metrics_snapshot_for_prompt(metrics_snapshot),
        ) if metrics_snapshot else "",
        _format_json_context(
            "COMPACT TOOL METHODOLOGY CARDS - INTERPRETATION ONLY",
            metrics_snapshot.get("methodology_cards", []),
        ) if metrics_snapshot else "",
        historical_block,
        _format_json_context("DECISION STATE - DETERMINISTIC PRECHECK", decision_state),
        _format_json_context("EVIDENCE PACKETS - BOUNDED CHILD TOOL OUTPUTS", evidence_packets),
    ]
    return "\n\n".join(section for section in sections if section)


def _write_ai_cio_context_sidecar(
    provider_key: str,
    decision_state: dict[str, Any],
    evidence_packets: list[dict[str, Any]],
    history_ledger: list[dict[str, Any]],
    metrics_snapshot: dict[str, Any] | None = None,
    metrics_snapshot_path: str | None = None,
) -> Path:
    """Persist the compact context sent to the final AI CIO prompt for audit/debug."""
    today_str = date.today().strftime('%d%m%y')
    path = DATA_LAKE / "daily_cache" / f"ai_cio_context_{provider_key}_{today_str}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider_key,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision_state": decision_state,
        "history_ledger": history_ledger,
        "evidence_packets": evidence_packets,
        "metrics_snapshot_path": metrics_snapshot_path,
        "metrics_snapshot": metrics_snapshot,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def run_executive_summary(api_key: str, provider_key: str = "kimi-2.6", force: bool = False,
                          source: str = "manual"):
    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["kimi-2.6"])
    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))
    model = cfg["api_model"]
    temperature = cfg.get("temperature", 1.0)
    
    # Nếu force=True → xoá cache AI text của các báo cáo con và executive_summary
    # để buộc gọi lại API từ đầu
    if force:
        _clear_all_tool_caches(provider_key)
    
    df_stocks = load_close_prices()
    
    # Ngày dữ liệu gần nhất trong data_lake (T-1 so với ngày xuất bản)
    data_date = df_stocks.index[-1].strftime('%d/%m/%Y')
    report_date = date.today().strftime('%d/%m/%Y')
    
    # Run tools (will use cache if already ran today)
    r1 = run_fear_greed(client, df_stocks, provider_key, model)
    r2 = run_manipulation(client, df_stocks, provider_key, model)
    r3 = run_dispersion(client, df_stocks, provider_key, model)
    r4 = run_upside_ratio(client, df_stocks, provider_key, model)
    r5 = run_bank_valuation(client, df_stocks, provider_key, model)
    r6 = run_market_breadth(client, df_stocks, provider_key, model)
    r7 = run_esr_monitor(client, df_stocks, provider_key, model)
    r8 = run_va_res(client, df_stocks, provider_key, model)
    r9 = run_var_cvar_vnindex(client, df_stocks, provider_key, model)
    r10 = run_sentiment_factor_news(client, provider_key, model)
    r11 = run_risk_adjusted_growth(client, df_stocks, provider_key, model)
    pvgo_context = build_pvgo_ai_cio_metric_context(coe_pct=14.0)
    humility_context = get_humility_falsification_context(provider_key, force=force)
    run_fed_liquidity_child_report(client, provider_key, model, force=force)
    run_global_financial_conditions_child_report(client, provider_key, model, force=force)
    run_credit_spread_child_report(client, provider_key, model, force=force)
    run_vnibor_child_report(client, provider_key, model, force=force)
    
    data_note = f"📅 Ngày xuất bản: {report_date} | Dữ liệu gần nhất trong data_lake: {data_date}"

    history_ledger = _read_recent_summary_ledger(provider_key, n_past=AI_CIO_HISTORY_WINDOW)
    historical_context = json.dumps(history_ledger, ensure_ascii=False, indent=2, default=str) if history_ledger else ""
    if historical_context:
        historical_block = (
            "=== AI CIO HISTORY LEDGER (UP TO 30 COMPACT ROWS; DETERMINISTIC, NO SUB-AI) ===\n"
            + historical_context
        )
    else:
        historical_block = "=== AI CIO HISTORY LEDGER: NO PRIOR HISTORY AVAILABLE ==="

    # Tải các báo cáo vĩ mô gần nhất (Lớp Vĩ mô - Macro Layer)
    fed_date, fed_rep = _get_fed_liquidity_context(provider_key)
    gfcm_date, gfcm_rep = _get_gfcm_context(provider_key)
    credit_spread_date, credit_spread_rep = _get_credit_spread_context(provider_key)
    margin_m2_date, margin_m2_rep = _build_margin_m2_structured_snapshot()
    vnibor_date, vnibor_rep = _get_vnibor_context(provider_key)
    ltmm_date, ltmm_rep = _build_ltmm_structured_context(provider_key)
    vn100_label, vn100_rep = _get_vn100_corporate_health_context(provider_key)
    abm_date, abm_rep = _build_abm_structured_snapshot()

    evidence_packets = [
        _build_evidence_packet("historical_trend", historical_block, "history", max_excerpt_chars=900),
        _build_evidence_packet("fed_liquidity", fed_rep, "macro", fed_date, max_excerpt_chars=900),
        _build_evidence_packet("global_financial_conditions", gfcm_rep, "macro", gfcm_date, max_excerpt_chars=900),
        _build_evidence_packet("credit_spread", credit_spread_rep, "macro", credit_spread_date, max_excerpt_chars=1100),
        _build_evidence_packet("margin_m2_overlay", margin_m2_rep, "macro", margin_m2_date, max_excerpt_chars=700),
        _build_evidence_packet("vnibor", vnibor_rep, "macro", vnibor_date, max_excerpt_chars=1000),
        _build_evidence_packet("ltmm", ltmm_rep, "macro", ltmm_date, max_excerpt_chars=2400),
        _build_evidence_packet("vn100_corporate_health", vn100_rep, "fundamental", vn100_label, max_excerpt_chars=1200),
        _build_evidence_packet("humility_falsification", humility_context, "audit", max_excerpt_chars=900),
        _build_evidence_packet("fear_greed", r1, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("manipulation", r2, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("dispersion", r3, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("upside_ratio", r4, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("bank_valuation", r5, "current_tool", data_date, max_excerpt_chars=900),
        _build_evidence_packet("market_breadth", r6, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("esr_monitor", r7, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("va_res", r8, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("var_cvar_vnindex", r9, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("abm_simulator", abm_rep, "tail_risk", abm_date, max_excerpt_chars=900),
        _build_evidence_packet("sentiment_factor_news", r10, "current_tool", data_date, max_excerpt_chars=700),
        _build_evidence_packet("risk_adjusted_growth", r11, "current_tool", data_date, max_excerpt_chars=900),
        _build_evidence_packet("pvgo", pvgo_context, "valuation", data_date, max_excerpt_chars=700),
    ]
    capitulation_state = _build_capitulation_state(df_stocks, evidence_packets)
    evidence_packets.append(_build_capitulation_evidence_packet(capitulation_state))
    decision_state = _build_decision_state(
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
        report_date=report_date,
        data_date=data_date,
    )
    decision_state = _attach_capitulation_policy(decision_state, capitulation_state)
    metrics_snapshot = _build_ai_cio_metrics_snapshot(
        provider_key=provider_key,
        report_date=report_date,
        data_date=data_date,
        decision_state=decision_state,
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
    )
    metrics_snapshot_path = _write_ai_cio_metrics_snapshot(metrics_snapshot)
    print(f"[AI CIO] Metrics snapshot: {metrics_snapshot_path}")
    all_reports = _build_ai_cio_structured_context(
        data_note=data_note,
        historical_block=historical_block,
        evidence_packets=evidence_packets,
        decision_state=decision_state,
        metrics_snapshot=metrics_snapshot,
    )
    context_sidecar_path = _write_ai_cio_context_sidecar(
        provider_key=provider_key,
        decision_state=decision_state,
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
        metrics_snapshot=metrics_snapshot,
        metrics_snapshot_path=str(metrics_snapshot_path),
    )
    print(f"[AI CIO] Structured context sidecar: {context_sidecar_path}")

    with open(str(ROOT_DIR / "promt" / "executive_summary_promt.md"), "r", encoding="utf-8") as f:
        master_prompt = f.read()

    master_full = master_prompt.replace("{all_reports}", all_reports)
    
    parts = master_full.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else master_full
    
    raw_final_res = call_ai(client, sys_p, usr_p, model=model, temperature=temperature)
    final_res, humility_rules_path = postprocess_executive_summary_report(
        raw_final_res,
        provider_key,
        decision_state=decision_state,
    )
    final_res = _enforce_final_score_regime(final_res, decision_state)
    final_res = _enforce_final_allocation_policy(final_res, decision_state)
    final_res = _annotate_final_score_drift(final_res, decision_state)
    final_score_value, final_regime_value = parse_score_regime(final_res)
    metrics_snapshot["final_output"] = {
        "score": _safe_float(final_score_value),
        "stress_regime": decision_state.get("final_stress_regime"),
        "resolved_regime": final_regime_value,
        "capitulation_override_active": decision_state.get("capitulation_override_active"),
        "confidence": decision_state.get("final_confidence"),
    }
    metrics_snapshot_path = _write_ai_cio_metrics_snapshot(metrics_snapshot)
    if humility_rules_path:
        print(f"[Humility] Saved rules JSON: {humility_rules_path}")
    _write_cache("executive_summary", final_res, provider_key)

    # ── Cập nhật history CSV (Ai_cio_report.csv) ──
    # Same-day overwrite: source="manual" sẽ ghi đè kết quả "auto" cùng ngày,
    # và ngược lại. Nếu sang ngày mới → append row mới. Semantic: kết quả mới
    # nhất là source-of-truth cho history page.
    try:
        score_val, regime_val = parse_score_regime(final_res)
        if score_val != "N/A":
            cap_state = decision_state.get("capitulation_state") or {}
            try:
                final_stress_regime = regime_from_score(float(score_val))
            except (TypeError, ValueError):
                final_stress_regime = str(decision_state.get("stress_regime") or "")
            ok = upsert_history_csv(
                score_val,
                regime_val,
                source=source,
                provider=provider_key,
                stress_regime=final_stress_regime,
                capitulation_phase=str(cap_state.get("phase") or ""),
                capitulation_action_eligible=cap_state.get("action_eligible"),
            )
            if ok:
                print(f"[CSV] Upserted history: {score_val} | {regime_val} | source={source} | provider={provider_key}")
        else:
            print("[CSV] Warning: không parse được final score → skip CSV update.")
    except Exception as exc:
        print(f"[CSV] Warning: upsert history failed ({exc}). Report vẫn được trả về.")

    return final_res
