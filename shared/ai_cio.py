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

# ── History CSV (Ai_cio_report.csv) ──
# Schema mới: ddmmyyyy, score, regime, source, provider
# Cũ chỉ có 3 cột — auto-migrate khi đọc.
CSV_HISTORY_PATH = DATA_LAKE / "Ai_cio_report.csv"
CSV_HISTORY_HEADER = ['ddmmyyyy', 'score', 'regime', 'source', 'provider']
AI_CIO_HISTORY_PROVIDER = "deepseek-v4-pro"
AI_CIO_METRICS_VERSION = "2.0"
AI_CIO_HISTORY_WINDOW = 30
AI_CIO_METRICS_DIRNAME = "ai_cio_metrics"
HUMILITY_RULES_PREFIX = "ai_cio_humility_rules"
TELEGRAM_SUMMARY_PREFIX = "telegram_summary"
TELEGRAM_SUMMARY_CHAR_LIMIT = 3500
AI_CIO_CACHE_VERSION_HEADER = "ai-cio-cache-version"
AI_CIO_TOOL_CACHE_VERSIONS: dict[str, str] = {
    "feargreed": "pca_point_in_time_v1",
    "global_financial_conditions": "pca_point_in_time_v1",
    "upside_ratio": "deterministic_mc_seed_v1",
    "var_cvar_vnindex": "evt_threshold_sensitivity_v1",
    "executive_summary": "ai_cio_methodology_v2",
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
        "primary_metric": "cqs_percentile_and_point_in_time_pc1",
        "score_direction": "Higher CQS percentile is worse for risk assets.",
        "limits": "PCA is expanding point-in-time with periodic refits; no full-history PCA backfit or look-ahead revision. Do not offset high credit stress with short-term news sentiment.",
        "authority": "Adapter score/regime/bias are authoritative when available.",
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
        "primary_metric": "vingroup_slope_percentile",
        "score_direction": "Higher coupling/concentration stress is worse.",
        "limits": "Mostly idiosyncratic/system-structure risk; do not overrule broad systemic tools alone.",
        "authority": "Use as concentration risk overlay unless adapter provides a hard score.",
    },
    "dispersion": {
        "domain": "market_structure_and_participation_quality",
        "horizon": "days_to_weeks",
        "primary_metric": "dispersion_pressure_index",
        "score_direction": "Health depends on whether dispersion confirms or undermines index moves.",
        "limits": "Low dispersion can mean idle/compressed risk, not automatically bullish.",
        "authority": "Use as soft market-internal evidence unless adapter provides a hard score.",
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
        "primary_metric": "contagion_complacency_modules",
        "score_direction": "Higher contagion/complacency stress is worse.",
        "limits": "Use for tail-risk color and avoid list; not a standalone composite score.",
        "authority": "Use as tail-risk evidence; adapter wins if present.",
    },
    "var_cvar_vnindex": {
        "domain": "left_tail_risk",
        "horizon": "days_to_weeks",
        "primary_metric": "evt_xi_with_threshold_sensitivity",
        "score_direction": "Higher EVT xi is worse.",
        "limits": "EVT threshold sensitivity is a robustness/confidence diagnostic, not a second bearish vote. A single high xi only becomes a hard cap when elevated/fat-tail classification is robust across thresholds.",
        "authority": "Adapter score/regime/bias are authoritative.",
    },
    "sentiment_factor_news": {
        "domain": "news_sentiment",
        "horizon": "1-3_days",
        "primary_metric": "news_sentiment_factor",
        "score_direction": "More positive news is supportive only at short horizon.",
        "limits": "Short-term noise; cannot veto macro, funding, breadth, or tail-risk stress.",
        "authority": "Use as soft overlay unless hard adapter exists.",
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
        "limits": "Not a crash timing signal; amplifies risk when breadth/liquidity/tail risk are weak.",
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
) -> bool:
    """Upsert (date, score, regime, source, provider) vào Ai_cio_report.csv.

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
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
from shared.data_loader import load_close_prices, load_custom, load_volumes

# Import logic Fear Greed
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import calculate_risk_score
from tools.upside_ratio.quant.metrics import build_breadth_series
from tools.upside_ratio.quant.engine import DEFAULT_MC_SEED, run_hybrid_ensemble_mc
# Import logic Manipulation
from tools.manipulation.quant.engine import prepare_data as prep_mani, compute_metrics as comp_mani, classify_regime
# Import logic Dispersion
from tools.dispersion.quant.metrics import calculate_dispersion_metrics, fit_rolling_correlation
# Import logic Upside Ratio

# Import logic Bank Valuation
from tools.bank_valuation.quant.engine.ai_analysis import build_bank_valuation_ai_prompt
from tools.bank_valuation.quant.pipeline import run_bank_valuation_pipeline
# Import logic Sentiment Factor From News
from tools.sentiment_factor_news.report import build_sentiment_factor_news_ai_prompt
# Import logic PVGO Valuation
from tools.pvgo.report import build_ai_cio_context as build_pvgo_ai_cio_context
# Import logic Market Breadth
from tools.market_breadth.quant.metrics import compute_breadth, top10_by_volume
# Import logic ESR Monitor
from tools.esr_monitor.quant.metrics import (
    run_esr_pipeline, VN30_TICKERS, PRODUCTION_REGIME_METHOD,
)
# Import logic VaRES Engine
from tools.va_res.report import snapshot as vares_snapshot
# Import logic Var-CVaR VNINDEX
from tools.var_cvar_vnindex.report import snapshot as var_cvar_snapshot
# Import Humility/Falsification audit context
from tools.humility_falsification.page import get_humility_falsification_context
from shared.ai_cio_scoring import derive_metric_implied_scores, regime_from_score, score_tool_packet

def _get_cache_path(tool_name: str, provider_key: str = "kimi-2.6") -> str:
    today_str = date.today().strftime('%d%m%y')
    return DATA_LAKE / "daily_cache" / f"{tool_name}_{provider_key}_{today_str}.txt"


def _cache_version_for_tool(tool_name: str) -> str | None:
    return AI_CIO_TOOL_CACHE_VERSIONS.get(str(tool_name or ""))


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
    return text[match.end():].lstrip("\r\n")


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
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8").strip()

    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["deepseek-v4-pro"])
    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))
    model = cfg["api_model"]
    temperature = min(float(cfg.get("temperature", 0.5)), 0.3)
    score_val, regime_val = parse_score_regime(report_text)
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

Full AI CIO report:
{report_text}
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


def postprocess_executive_summary_report(report_text: str, provider_key: str) -> tuple[str, Path | None]:
    """Strip the machine JSON block from the human report and save it as a sidecar file."""

    payload, span = _extract_falsification_payload(report_text)
    clean_text = report_text
    if span is not None:
        clean_text = f"{report_text[:span[0]].rstrip()}\n\n{report_text[span[1]:].lstrip()}".strip()
    elif '"falsification_rules"' in report_text:
        clean_text = _strip_incomplete_falsification_block(report_text)

    if payload is None and '"falsification_rules"' in report_text:
        payload = _fallback_humility_payload_from_markdown(clean_text)

    sidecar_path = _write_humility_rules_payload(payload, provider_key) if payload else None

    score_val, regime_val = parse_score_regime(clean_text)
    if score_val == "N/A" and payload:
        score_val = _payload_number_as_text(payload.get("composite_score"))
    if regime_val == "N/A" and payload:
        regime_val = _clean_regime_value(str(payload.get("regime", ""))) or "N/A"
    if score_val == "N/A" or regime_val == "N/A":
        fallback_score, fallback_regime = parse_score_regime(report_text)
        if score_val == "N/A":
            score_val = fallback_score
        if regime_val == "N/A":
            regime_val = fallback_regime

    if score_val != "N/A" and regime_val != "N/A" and not _has_final_score_line(clean_text):
        clean_text = clean_text.rstrip() + f"\n\nfinal score & regime : {score_val} ; regime : {regime_val}\n"

    return clean_text, sidecar_path


def _score_band_for_regime(regime: str) -> tuple[int, int] | None:
    normalized = _clean_regime_value(regime).upper()
    if normalized == "CAPITULATION":
        return 0, 7
    if normalized == "EXTREME CRISIS":
        return 8, 14
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
    drift = final_score - baseline
    drift_alert_points = int(decision_state.get("drift_alert_points") or 8)
    baseline_band = _score_band_for_regime(baseline_regime)
    final_in_baseline_band = baseline_band[0] <= final_score <= baseline_band[1] if baseline_band else True

    flags: list[str] = []
    if abs(drift) >= drift_alert_points:
        flags.append(f"large overlay drift {drift:+d} points versus metric_implied_score={baseline}")
    if not final_in_baseline_band:
        flags.append(f"final score moved outside metric-implied band {baseline_regime}")
    if final_regime not in ("", "N/A") and final_regime != score_regime:
        flags.append(f"reported regime {final_regime} differs from score-matrix regime {score_regime}")
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
        "overlay",
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


def _extract_first_number(patterns: list[str], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1).replace(",", ""))
        except Exception:
            continue
    return None


def _build_evidence_packet(
    tool_id: str,
    report_text: str,
    layer: str,
    date_label: str | None = None,
    max_excerpt_chars: int = 1400,
) -> dict[str, Any]:
    """Convert a verbose child report into a bounded evidence packet for AI CIO."""
    text = str(report_text or "").strip()
    score_val, regime_val = parse_score_regime(text)
    packet: dict[str, Any] = {
        "tool": tool_id,
        "layer": layer,
        "date": date_label or "N/A",
        "bias": _infer_evidence_bias(text),
        "score": None if score_val == "N/A" else score_val,
        "regime": None if regime_val == "N/A" else regime_val,
        "key_metrics": {},
        "evidence_excerpt": _compact_text(text, max_chars=max_excerpt_chars),
    }

    metric_patterns = {
        "ssi_pct": [r"\bSSI\b[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "evt_xi": [r"\bxi\b[^0-9-]*([-+]?\d+(?:\.\d+)?)", r"Tail Index.*?([-+]?\d+(?:\.\d+)?)"],
        "evt_xi_min": [r"EVT\s+Xi\s+Min[^0-9-]*([-+]?\d+(?:\.\d+)?)", r"\bxi_min\b[^0-9-]*([-+]?\d+(?:\.\d+)?)"],
        "evt_xi_max": [r"EVT\s+Xi\s+Max[^0-9-]*([-+]?\d+(?:\.\d+)?)", r"\bxi_max\b[^0-9-]*([-+]?\d+(?:\.\d+)?)"],
        "evt_xi_range": [r"EVT\s+Xi\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)", r"\bxi_range\b[^0-9-]*([-+]?\d+(?:\.\d+)?)"],
        "evt_var99_range_pp": [r"EVT\s+VaR99\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*pp"],
        "evt_es99_range_pp": [r"EVT\s+ES99\s+Range[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*pp"],
        "evt_threshold_stable": [r"EVT\s+Threshold\s+Stable[^0-9]*(0|1)"],
        "breadth_ma20_pct": [r"MA20[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "cqs_percentile": [
            r"\bCQS\s+Percentile\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bCQS\b[^\n]*?percentile[^0-9-]*([-+]?\d+(?:\.\d+)?)",
            r"\bCQS\b[^0-9-]*([-+]?\d+(?:\.\d+)?)",
        ],
        "vnibor_on": [r"Overnight[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "pvgo_pct": [r"\bPVGO\b\s*:\s*([-+]?\d+(?:\.\d+)?)\s*%"],
        "pe": [r"\bP/E\b\s*:\s*([-+]?\d+(?:\.\d+)?)x"],
        "coe_pct": [r"\bCOE assumption\b\s*:\s*([-+]?\d+(?:\.\d+)?)\s*%"],
        "distance_to_cascade_pct": [r"Distance to Cascade[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "panic_ratio_pct": [r"(?:Simulated\s+)?Panic Ratio[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "abm_early_warning_score": [r"Early-warning Score[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*(?:/100)?"],
        "abm_avg_leverage_ratio": [r"Avg Leverage Ratio[^0-9-]*([-+]?\d+(?:\.\d+)?)x?"],
        "cascade_vulnerability": [r"Cascade Vulnerability[^0-9-]*([-+]?\d+(?:\.\d+)?)"],
        "abm_stress_confidence_pct": [r"Stress Confidence[^0-9-]*([-+]?\d+(?:\.\d+)?)\s*%"],
        "ltmm_fli": [r"LTMM\s+FLI\s*:\s*([-+]?\d+(?:\.\d+)?)"],
        "ltmm_mli": [r"LTMM\s+MLI\s*:\s*([-+]?\d+(?:\.\d+)?)"],
        "ltmm_te": [r"LTMM\s+TE\s*:\s*([-+]?\d+(?:\.\d+)?)"],
        "ltmm_fri_collateral": [r"LTMM\s+FRI_collateral\s*:\s*([-+]?\d+(?:\.\d+)?)"],
        "ltmm_fire_trigger_count": [r"LTMM\s+Fire\s+Trigger\s+Count\s*:\s*(\d+)"],
        "ltmm_transmission_breakdown_fire": [r"(?:LTMM\s+)?transmission_breakdown\s+FIRE\s*:\s*(\d+)"],
    }
    for metric, patterns in metric_patterns.items():
        value = _extract_first_number(patterns, text)
        if value is not None:
            packet["key_metrics"][metric] = value
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


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return None
        return float(value)
    except Exception:
        return None


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

    rows = sorted(history_ledger or [], key=_history_row_sort_key)
    compact_history: list[dict[str, Any]] = []
    for row in rows[-AI_CIO_HISTORY_WINDOW:]:
        score = _safe_float(row.get("score"))
        compact_history.append(
            {
                "date": row.get("date"),
                "score": None if score is None else int(round(score)),
                "regime": row.get("regime", "N/A"),
                "source": row.get("source", ""),
                "provider": row.get("provider", ""),
            }
        )

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
        metrics = packet.get("key_metrics") or {}
        adapter_score = packet.get("adapter_score")
        if not isinstance(adapter_score, dict):
            adapter_score = score_tool_packet(tool, metrics)
        tools[tool] = {
            "tool": tool,
            "layer": packet.get("layer"),
            "as_of": packet.get("date"),
            "bias": packet.get("bias"),
            "report_score": packet.get("score"),
            "report_regime": packet.get("regime"),
            "key_metrics": metrics,
            "adapter_available": isinstance(adapter_score, dict),
            "tool_score": adapter_score.get("tool_score") if isinstance(adapter_score, dict) else None,
            "tool_regime": adapter_score.get("tool_regime") if isinstance(adapter_score, dict) else None,
            "tool_bias": adapter_score.get("tool_bias") if isinstance(adapter_score, dict) else None,
            "score_reason": adapter_score.get("score_reason") if isinstance(adapter_score, dict) else None,
            "data_quality": "structured_adapter" if isinstance(adapter_score, dict) else "soft_excerpt_only",
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
        current_regime=decision_state.get("metric_implied_regime"),
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
            "Adapter tool_score/tool_regime/tool_bias are authoritative when present.",
            "LLM may explain or lightly overlay, but must not relabel adapter outputs from prose.",
            "History is for persistence/delta only; it must not anchor today's final score.",
            "Human report excerpts are supporting evidence, not the scoring source of truth.",
        ],
        "score_anchor": {
            "metric_implied_score": decision_state.get("metric_implied_score"),
            "metric_implied_regime": decision_state.get("metric_implied_regime"),
            "metric_implied_subscores": decision_state.get("metric_implied_subscores"),
            "score_band_reason": decision_state.get("score_band_reason"),
            "hard_constraints": decision_state.get("hard_constraints"),
        },
        "consensus": decision_state.get("consensus_map"),
        "tools": _build_tool_metrics_snapshot(evidence_packets),
        "history": history,
        "methodology_cards": methodology_cards,
    }


def _get_ai_cio_metrics_snapshot_path(target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / AI_CIO_METRICS_DIRNAME / f"metrics_{date_key}.json"


def _write_ai_cio_metrics_snapshot(snapshot: dict[str, Any], target_date: date | None = None) -> Path:
    path = _get_ai_cio_metrics_snapshot_path(target_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    path.write_text(payload, encoding="utf-8")
    latest_path = path.parent / "latest.json"
    latest_path.write_text(payload, encoding="utf-8")
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
                    rows.append(
                        {
                            "date": row_date.isoformat(),
                            "score": row.get("score", "N/A"),
                            "regime": row.get("regime", "N/A"),
                            "source": row.get("source", ""),
                            "provider": row.get("provider", ""),
                        }
                    )
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
            content = path.read_text(encoding="utf-8").strip()
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
            df_stocks, df_vn30, df_volume=df_volume, deposit_rate=0.06,
            pillar_mode='downside', pca_warmup=252, ema_span=20, regime_method=PRODUCTION_REGIME_METHOD
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
        "fed_liquidity", "global_financial_conditions",
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
    
    status_text = "EXTREME FEAR" if score <= 20 else "FEAR" if score <= 40 else "NEUTRAL / STOCK PICKING" if score < 60 else "GREED" if score < 80 else "EXTREME GREED"

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
                                 
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    res = _append_structured_footer(
        res,
        "fear_greed_methodology",
        [
            f"FearGreed Risk Score: {score:.1f}",
            "PCA Method: expanding_point_in_time",
            "PCA Full-History Fit: 0",
            "PCA Refit Every Sessions: 21",
        ],
    )
    _write_cache("feargreed", res, provider_key)
    return res

def run_manipulation(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("manipulation", provider_key)
    if cached: return cached

    df_prices = prep_mani(df_stocks)
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

    # ── Inject giá real-time VIC/VHM/VRE + VN30F1M để chống AI hallucinate
    # mức giá cũ (vd. "VIC mất 45,000" trong khi VIC hiện ~200k). df_prices từ
    # prep_mani() có sẵn 4 cột [VIC, VHM, VRE, VN30F1M].
    # Cổ phiếu: market_data.csv lưu theo nghìn VND → *1000 ra VND đầy đủ.
    # F1M: là futures index, đơn vị "điểm" (~VN30 index level) — KHÔNG nhân 1000.
    def _fmt_stock_price(value: float) -> str:
        if pd.isna(value) or value <= 0:
            return "N/A"
        return f"{value:.2f} (≈ {int(value * 1000):,} VND)"

    def _fmt_futures_index(value: float) -> str:
        if pd.isna(value) or value <= 0:
            return "N/A"
        return f"{value:,.2f} điểm (VN30 index level)"

    last_prices = df_prices.iloc[-1]
    vic_close = _fmt_stock_price(last_prices.get("VIC", float("nan")))
    vhm_close = _fmt_stock_price(last_prices.get("VHM", float("nan")))
    vre_close = _fmt_stock_price(last_prices.get("VRE", float("nan")))
    f1m_close = _fmt_futures_index(last_prices.get("VN30F1M", float("nan")))

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
                                 .replace("{f1m_close}", f1m_close)

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
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
    metrics = metrics.dropna(subset=["DPI", "Ledoit_Correlation"])
    
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

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
    _write_cache("dispersion", res, provider_key)
    return res

def run_upside_ratio(client, df_stocks, provider_key: str = "kimi-2.6", model: str = None):
    cached = _read_cache("upside_ratio", provider_key)
    if cached: return cached
    
    data = build_breadth_series(df_stocks, upside_x=2.0, downside_y=-2.0, lookback_days=90)
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
            "MC Interpretation: scenario_diagnostic_not_allocation_authority",
        ],
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
        deposit_rate=0.06,
        pillar_mode='downside',
        pca_warmup=252,
        ema_span=20,
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
    full_prompt = full_prompt.replace("[Pillar Mode]", "downside")
    if "[Threshold]" in full_prompt:
        full_prompt = full_prompt.replace("[Threshold]", f"{threshold:.3f}" if threshold is not None else "N/A")

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
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
    
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_ai(client, sys_p, usr_p, model=model)
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
            .replace("[EVT Xi]", f"{snap['evt_xi']:+.3f} ({xi_label})")\
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
    else:
        # Data < 756 ngày — bỏ EVT fields, AI prompt vẫn chạy với classic metrics
        for placeholder in [
            "[EVT VaR 99%]", "[EVT VaR 99.5%]", "[EVT ES 99%]",
            "[EVT Xi]", "[Hill Index]", "[EVT N Exceed]",
            "[EVT Xi Min]", "[EVT Xi Max]", "[EVT Xi Range]",
            "[EVT VaR99 Range]", "[EVT ES99 Range]",
            "[EVT Threshold Stable]", "[EVT Sensitivity Status]",
        ]:
            full_prompt = full_prompt.replace(placeholder, "N/A (cần ≥ 756 phiên)")

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

    res = call_ai(client, sys_p, usr_p, model=model)
    footer_lines = ["EVT Method: POT_GPD_threshold_sensitivity_5_15pct"]
    if snap.get("evt_available"):
        footer_lines.extend(
            [
                f"EVT Xi: {snap['evt_xi']:+.3f}",
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
    res = _append_structured_footer(res, "var_cvar_vnindex_methodology", footer_lines)
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
            f"CQS Percentile: {summary['cqs_pct']*100:.1f}",
            f"PC1 Percentile: {summary['pc1_pct']*100:.1f}",
            "PCA Method: expanding_point_in_time",
            "PCA Full-History Fit: 0",
            "PCA Refit Every Sessions: 21",
        ],
    )
    _write_cache("global_financial_conditions", result, provider_key)
    return result


def _get_gfcm_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Read the latest Global FCI child AI report."""
    return _get_latest_report_for_macro("global_financial_conditions", provider_key)


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
    return label, snapshot


def _get_vnibor_context(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Combine structured VNIBOR trend with optional cached VNIBOR AI report."""
    snapshot_date, snapshot = _build_vnibor_structured_trend()
    ai_date, ai_report = _get_latest_report_for_macro("vnibor", provider_key)
    if ai_report and not ai_report.startswith("*Chưa có"):
        context = (
            f"{snapshot}\n\n"
            f"=== VNIBOR AI INTERPRETATION CACHE (Ngày báo cáo: {ai_date}) ===\n"
            f"{ai_report}"
        )
    else:
        context = (
            f"{snapshot}\n\n"
            "=== VNIBOR AI INTERPRETATION CACHE ===\n"
            "*Chưa có cache AI riêng của VNIBOR; AI CIO phải tự diễn giải từ structured snapshot + 20D trend phía trên.*"
        )
    return snapshot_date, context


def _get_latest_vn100_ai_report(provider_key: str = "kimi-2.6") -> tuple[str, str]:
    """Return latest cached VN100 AI interpretation for this provider, with fallback to any provider."""
    import datetime as datetime_mod

    cache_dir = DATA_LAKE / "daily_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    files = list(cache_dir.glob(f"vn100_earnings_health_{provider_key}_*.txt"))
    if not files:
        files = list(cache_dir.glob("vn100_earnings_health_*.txt"))
    if not files:
        return "N/A", ""

    def file_sort_key(p: Path):
        file_date = _parse_date_from_filename(p.stem)
        if file_date:
            return (file_date, p.stat().st_mtime)
        return (date(1970, 1, 1), p.stat().st_mtime)

    latest_file = sorted(files, key=file_sort_key, reverse=True)[0]
    parsed_date = _parse_date_from_filename(latest_file.stem)
    if parsed_date:
        date_str = parsed_date.strftime("%d/%m/%Y")
    else:
        mtime = datetime_mod.datetime.fromtimestamp(latest_file.stat().st_mtime)
        date_str = mtime.strftime("%d/%m/%Y")

    try:
        return date_str, latest_file.read_text(encoding="utf-8").strip()
    except Exception as e:
        return "N/A", f"Lỗi đọc file VN100 AI cache: {e}"


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
        if tool in scored_tools:
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
    bias_counts = {
        "bullish": sum(1 for packet in current_packets if packet.get("bias") == "bullish"),
        "bearish": sum(1 for packet in current_packets if packet.get("bias") == "bearish"),
        "neutral_or_mixed": sum(1 for packet in current_packets if packet.get("bias") == "neutral_or_mixed"),
    }
    hard_constraints: list[str] = []
    metric_values: dict[str, Any] = {}
    tool_scores: list[dict[str, Any]] = []
    for packet in current_packets:
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
            "Do not place final score in 8-14 solely because recent history was 11-13.",
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
    pvgo_context = build_pvgo_ai_cio_context(coe_pct=14.0)
    humility_context = get_humility_falsification_context(provider_key, force=force)
    run_fed_liquidity_child_report(client, provider_key, model, force=force)
    run_global_financial_conditions_child_report(client, provider_key, model, force=force)
    
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
    margin_m2_date, margin_m2_rep = _build_margin_m2_structured_snapshot()
    vnibor_date, vnibor_rep = _get_vnibor_context(provider_key)
    ltmm_date, ltmm_rep = _build_ltmm_structured_context(provider_key)
    vn100_label, vn100_rep = _get_vn100_corporate_health_context(provider_key)
    abm_date, abm_rep = _build_abm_structured_snapshot()

    evidence_packets = [
        _build_evidence_packet("historical_trend", historical_block, "history", max_excerpt_chars=900),
        _build_evidence_packet("fed_liquidity", fed_rep, "macro", fed_date, max_excerpt_chars=900),
        _build_evidence_packet("global_financial_conditions", gfcm_rep, "macro", gfcm_date, max_excerpt_chars=900),
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
    decision_state = _build_decision_state(
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
        report_date=report_date,
        data_date=data_date,
    )
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
    final_res, humility_rules_path = postprocess_executive_summary_report(raw_final_res, provider_key)
    final_res = _annotate_final_score_drift(final_res, decision_state)
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
            ok = upsert_history_csv(score_val, regime_val,
                                    source=source, provider=provider_key)
            if ok:
                print(f"[CSV] Upserted history: {score_val} | {regime_val} | source={source} | provider={provider_key}")
        else:
            print("[CSV] Warning: không parse được final score → skip CSV update.")
    except Exception as exc:
        print(f"[CSV] Warning: upsert history failed ({exc}). Report vẫn được trả về.")

    return final_res
