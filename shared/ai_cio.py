import csv
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import pandas as pd
import streamlit as st
from openai import OpenAI
from config import DATA_LAKE, ROOT_DIR, AI_MODEL, AI_TEMPERATURE

# ── History CSV (Ai_cio_report.csv) ──
# Schema mới: ddmmyyyy, score, regime, source, provider
# Cũ chỉ có 3 cột — auto-migrate khi đọc.
CSV_HISTORY_PATH = DATA_LAKE / "Ai_cio_report.csv"
CSV_HISTORY_HEADER = ['ddmmyyyy', 'score', 'regime', 'source', 'provider']
HUMILITY_RULES_PREFIX = "ai_cio_humility_rules"
TELEGRAM_SUMMARY_PREFIX = "telegram_summary"
TELEGRAM_SUMMARY_CHAR_LIMIT = 3500
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
        "metric": "Tail Index (xi)",
        "threshold_operator": "<",
        "threshold_value": 0.25,
        "unit": "",
        "description": "Left-tail risk normalizes when the EVT tail index falls below 0.25.",
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
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
from shared.data_loader import load_close_prices, load_custom, load_volumes

# Import logic Fear Greed
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import calculate_risk_score
from tools.upside_ratio.quant.metrics import build_breadth_series
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc
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

def _get_cache_path(tool_name: str, provider_key: str = "kimi-2.6") -> str:
    today_str = date.today().strftime('%d%m%y')
    return DATA_LAKE / "daily_cache" / f"{tool_name}_{provider_key}_{today_str}.txt"

def _read_cache(tool_name: str, provider_key: str = "kimi-2.6") -> str:
    path = _get_cache_path(tool_name, provider_key)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None

def _write_cache(tool_name: str, content: str, provider_key: str = "kimi-2.6"):
    path = _get_cache_path(tool_name, provider_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _get_humility_rules_path(provider_key: str, target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{HUMILITY_RULES_PREFIX}_{provider_key}_{date_key}.json"


def get_telegram_summary_path(provider_key: str, target_date: date | None = None) -> Path:
    date_key = (target_date or date.today()).strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{TELEGRAM_SUMMARY_PREFIX}_{provider_key}_{date_key}.txt"


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

    system_prompt = (
        "You are a portfolio risk chief writing a concise Vietnamese Telegram brief. "
        "Compress the AI CIO report into an action-oriented daily decision note. "
        "Use only facts in the report. Do not add prices or new tickers. "
        "If the report contains section 5.5 LLM Overlay, explicitly summarize the "
        "metric-implied score, overlay adjustment, and final CIO score in one line. "
        "Keep the output under 2300 Vietnamese characters. Plain text only; no Markdown tables, no JSON."
    )
    user_prompt = f"""
REPORT DATE: {target_date.strftime('%d/%m/%Y')}
PARSED SCORE: {score_val}
PARSED REGIME: {regime_val}

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

def _read_recent_summaries(provider_key: str = "kimi-2.6", n_past: int = 5) -> str:
    """Đọc tối đa n_past báo cáo executive_summary gần nhất.
    Quét lùi tối đa 25 ngày lịch để bỏ qua ngày nghỉ/không có cache.
    Trả về chuỗi context sẵn sàng chèn vào prompt, rỗng nếu không tìm thấy."""
    cache_dir = DATA_LAKE / "daily_cache"
    found = []
    for days_back in range(1, 26):
        if len(found) >= n_past:
            break
        target_date = date.today() - timedelta(days=days_back)
        date_str = target_date.strftime('%d%m%y')
        path = cache_dir / f"executive_summary_{provider_key}_{date_str}.txt"
        if not path.exists():
            # Fallback sang bất kỳ model/provider nào khác có sẵn báo cáo cho ngày này
            alt_paths = list(cache_dir.glob(f"executive_summary_*_{date_str}.txt"))
            if alt_paths:
                path = alt_paths[0]
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            label = f"T-{len(found)+1} ({target_date.strftime('%d/%m/%Y')})"
            found.append((label, content))

    if not found:
        return ""

    blocks = []
    for label, content in found:
        blocks.append(f"=== BÁO CÁO {label} ===\n{content}")
    return "\n\n".join(blocks)

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
        gfcm_path = DATA_LAKE / "global_financial_conditions_cache.csv"
        df_gfcm = pd.read_csv(gfcm_path, parse_dates=["DATE"]).set_index("DATE").sort_index()
        
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
    slope_pr = latest["PR_Slope"] * 100
    slope_status = "🔴 Cao" if slope_pr >= 80 else "🟢 Thấp" if slope_pr <= 20 else "🟡 Trung bình"

    corr_val = latest["Correlation"]
    corr_pr = latest["PR_Corr"] * 100
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
    up_tuple = run_hybrid_ensemble_mc(data["raw_upside"], days_to_sim=20, num_sims=5000)
    dn_tuple = run_hybrid_ensemble_mc(data["raw_downside"], days_to_sim=20, num_sims=5000)
    
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
    else:
        # Data < 756 ngày — bỏ EVT fields, AI prompt vẫn chạy với classic metrics
        for placeholder in ["[EVT VaR 99%]", "[EVT VaR 99.5%]", "[EVT ES 99%]",
                            "[EVT Xi]", "[Hill Index]", "[EVT N Exceed]"]:
            full_prompt = full_prompt.replace(placeholder, "N/A (cần ≥ 756 phiên)")

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

    res = call_ai(client, sys_p, usr_p, model=model)
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
    latest_file = files[0]
    
    # Phân tích ngày từ tên file để hiển thị
    date_str = "N/A"
    parsed_date = _parse_date_from_filename(latest_file.stem)
    if parsed_date:
        date_str = parsed_date.strftime('%d/%m/%Y')
    else:
        mtime = datetime_mod.datetime.fromtimestamp(latest_file.stat().st_mtime)
        date_str = mtime.strftime('%d/%m/%Y')
            
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return date_str, content
    except Exception as e:
        return "N/A", f"Lỗi đọc file: {e}"


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
    humility_context = get_humility_falsification_context(provider_key, force=force)
    run_fed_liquidity_child_report(client, provider_key, model, force=force)
    run_global_financial_conditions_child_report(client, provider_key, model, force=force)
    
    data_note = f"📅 Ngày xuất bản: {report_date} | Dữ liệu gần nhất trong data_lake: {data_date}"

    historical_context = _read_recent_summaries(provider_key, n_past=7)
    if historical_context:
        print(f"[Trend Analyst] Generating 7-day historical trend summary via Sub AI CIO...")
        trend_summary = run_historical_trend_analyst(
            client, provider_key=provider_key, model=model,
            raw_history_text=historical_context, force=force
        )
        historical_block = (
            "=== BẢN TÓM TẮT XU HƯỚNG LỊCH SỬ (T-1 ĐẾN T-7 — DO SUB AI CIO TÓM TẮT) ===\n"
            + trend_summary
        )
    else:
        historical_block = "=== BẢN TÓM TẮT XU HƯỚNG LỊCH SỬ: Không có cache T-1 đến T-7 ==="

    # Tải các báo cáo vĩ mô gần nhất (Lớp Vĩ mô - Macro Layer)
    fed_date, fed_rep = _get_fed_liquidity_context(provider_key)
    gfcm_date, gfcm_rep = _get_gfcm_context(provider_key)
    margin_m2_date, margin_m2_rep = _build_margin_m2_structured_snapshot()
    vnibor_date, vnibor_rep = _get_vnibor_context(provider_key)
    ltmm_date, ltmm_rep = _get_latest_report_for_macro("ltmm", provider_key)
    vn100_label, vn100_rep = _get_vn100_corporate_health_context(provider_key)

    macro_section = (
        "=== BÁO CÁO PHÂN TÍCH VĨ MÔ GẦN NHẤT (MACRO LAYER) ===\n\n"
        f"=== A. FED LIQUIDITY MONITOR (Ngày báo cáo: {fed_date}) ===\n{fed_rep}\n\n"
        f"=== B. GLOBAL FINANCIAL CONDITIONS (Ngày báo cáo: {gfcm_date}) ===\n{gfcm_rep}\n\n"
        f"=== B2. US MARGIN DEBT / M2 OVERLAY (Kỳ dữ liệu: {margin_m2_date}) ===\n{margin_m2_rep}\n\n"
        f"=== C. VNIBOR MONITOR (Ngày báo cáo: {vnibor_date}) ===\n{vnibor_rep}\n\n"
        f"=== D. LIQUIDITY TRANSMISSION - LTMM (Ngày báo cáo: {ltmm_date}) ===\n{ltmm_rep}\n\n"
    )

    fundamental_section = (
        "=== BÁO CÁO FUNDAMENTAL BOTTOM-UP - VN100 CORPORATE HEALTH ===\n\n"
        f"=== VN100 CORPORATE HEALTH MONITOR (Kỳ dữ liệu: {vn100_label}) ===\n{vn100_rep}\n\n"
    )

    all_reports = (
        f"=== {data_note} ===\n\n"
        f"{historical_block}\n\n"
        f"{macro_section}"
        f"{fundamental_section}"
        f"=== HUMILITY & FALSIFICATION MONITOR (T vs PRIOR AI CIO THESIS) ===\n{humility_context}\n\n"
        f"=== BÁO CÁO HIỆN TẠI (T) ===\n\n"
        f"=== 1. FEAR & GREED ===\n{r1}\n\n"
        f"=== 2. MANIPULATION ===\n{r2}\n\n"
        f"=== 3. DISPERSION ===\n{r3}\n\n"
        f"=== 4. UPSIDE RATIO ===\n{r4}\n\n"
        f"=== 5. BANK VALUATION ===\n{r5}\n\n"
        f"=== 6. MARKET BREADTH ===\n{r6}\n\n"
        f"=== 7. ESR MONITOR ===\n{r7}\n\n"
        f"=== 8. VARES ENGINE ===\n{r8}\n\n"
        f"=== 9. VAR-CVAR VNINDEX ===\n{r9}\n\n"
        f"=== 10. SENTIMENT FACTOR FROM NEWS ===\n{r10}\n\n"
        f"=== 11. RISK-ADJUSTED GROWTH ===\n{r11}"
    )

    with open(str(ROOT_DIR / "promt" / "executive_summary_promt.md"), "r", encoding="utf-8") as f:
        master_prompt = f.read()

    master_full = master_prompt.replace("{all_reports}", all_reports)
    
    parts = master_full.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else master_full
    
    raw_final_res = call_ai(client, sys_p, usr_p, model=model, temperature=temperature)
    final_res, humility_rules_path = postprocess_executive_summary_report(raw_final_res, provider_key)
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
