from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import AI_PROVIDER_MAP, DATA_LAKE, ROOT_DIR
from shared import ai_cio


CURRENT_TOOL_CACHE_MAP = [
    ("fear_greed", "feargreed", "current_tool", 700),
    ("manipulation", "manipulation", "current_tool", 700),
    ("dispersion", "dispersion", "current_tool", 700),
    ("upside_ratio", "upside_ratio", "current_tool", 700),
    ("bank_valuation", "bank_valuation_ai", "current_tool", 900),
    ("market_breadth", "market_breadth", "current_tool", 700),
    ("esr_monitor", "esr_monitor", "current_tool", 700),
    ("va_res", "va_res", "current_tool", 700),
    ("var_cvar_vnindex", "var_cvar_vnindex", "current_tool", 700),
    ("sentiment_factor_news", "sentiment_factor_news", "current_tool", 700),
    ("risk_adjusted_growth", "risk_adjusted_growth", "current_tool", 900),
]


def _file_sort_key(path: Path) -> tuple[date, float]:
    parsed = ai_cio._parse_date_from_filename(path.stem)
    return (parsed or date(1970, 1, 1), path.stat().st_mtime)


def _read_latest_cache(cache_name: str, provider_key: str) -> tuple[str, str]:
    cache_dir = DATA_LAKE / "daily_cache"
    files = list(cache_dir.glob(f"{cache_name}_{provider_key}_*.txt"))
    if not files:
        files = list(cache_dir.glob(f"{cache_name}_*.txt"))
    if not files:
        return (
            "N/A",
            f"DATA INSUFFICIENT: No cached report found for {cache_name} / provider={provider_key}. "
            "Prompt export did not call the LLM to regenerate it.",
        )

    for latest in sorted(files, key=_file_sort_key, reverse=True):
        content = ai_cio._read_cache_file(latest, cache_name)
        if content is None:
            continue
        parsed = ai_cio._parse_date_from_filename(latest.stem)
        date_label = parsed.strftime("%d/%m/%Y") if parsed else "N/A"
        return date_label, content.strip()

    version = ai_cio._cache_version_for_tool(cache_name)
    version_note = f" current cache version {version}" if version else ""
    return (
        "N/A",
        f"DATA INSUFFICIENT: No cached report found for {cache_name} / provider={provider_key}"
        f" matching{version_note}. Prompt export did not call the LLM to regenerate it.",
    )


def _build_current_tool_packets(provider_key: str, data_date: str) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for tool_id, cache_name, layer, max_excerpt_chars in CURRENT_TOOL_CACHE_MAP:
        cache_date, report_text = _read_latest_cache(cache_name, provider_key)
        packet_date = cache_date if cache_date != "N/A" else data_date
        packets.append(
            ai_cio._build_evidence_packet(
                tool_id,
                report_text,
                layer,
                packet_date,
                max_excerpt_chars=max_excerpt_chars,
            )
        )
    return packets


def build_ai_cio_prompt_payload(provider_key: str) -> dict[str, Any]:
    if provider_key not in AI_PROVIDER_MAP:
        valid = ", ".join(AI_PROVIDER_MAP)
        raise ValueError(f"Unknown provider '{provider_key}'. Valid providers: {valid}")

    df_stocks = ai_cio.load_close_prices()
    data_date = df_stocks.index[-1].strftime("%d/%m/%Y")
    report_date = date.today().strftime("%d/%m/%Y")
    data_note = f"📅 Ngày xuất bản: {report_date} | Dữ liệu gần nhất trong data_lake: {data_date}"

    history_ledger = ai_cio._read_recent_summary_ledger(
        provider_key,
        n_past=ai_cio.AI_CIO_HISTORY_WINDOW,
    )
    if history_ledger:
        historical_block = (
            "=== AI CIO HISTORY LEDGER (UP TO 30 COMPACT ROWS; DETERMINISTIC, NO SUB-AI) ===\n"
            + json.dumps(history_ledger, ensure_ascii=False, indent=2, default=str)
        )
    else:
        historical_block = "=== AI CIO HISTORY LEDGER: NO PRIOR HISTORY AVAILABLE ==="

    fed_date, fed_rep = ai_cio._get_fed_liquidity_context(provider_key)
    gfcm_date, gfcm_rep = ai_cio._get_gfcm_context(provider_key)
    credit_spread_date, credit_spread_rep = ai_cio._get_credit_spread_context(provider_key)
    margin_m2_date, margin_m2_rep = ai_cio._build_margin_m2_structured_snapshot()
    vnibor_date, vnibor_rep = ai_cio._get_vnibor_context(provider_key)
    ltmm_date, ltmm_rep = ai_cio._build_ltmm_structured_context(provider_key)
    vn100_label, vn100_rep = ai_cio._get_vn100_corporate_health_context(provider_key)
    abm_date, abm_rep = ai_cio._build_abm_structured_snapshot()
    pvgo_context = ai_cio.build_pvgo_ai_cio_metric_context(coe_pct=14.0)
    humility_context = ai_cio.get_humility_falsification_context(provider_key, force=False)
    current_packets = {
        packet["tool"]: packet
        for packet in _build_current_tool_packets(provider_key, data_date)
    }

    evidence_packets = [
        ai_cio._build_evidence_packet("historical_trend", historical_block, "history", max_excerpt_chars=900),
        ai_cio._build_evidence_packet("fed_liquidity", fed_rep, "macro", fed_date, max_excerpt_chars=900),
        ai_cio._build_evidence_packet("global_financial_conditions", gfcm_rep, "macro", gfcm_date, max_excerpt_chars=900),
        ai_cio._build_evidence_packet("credit_spread", credit_spread_rep, "macro", credit_spread_date, max_excerpt_chars=1100),
        ai_cio._build_evidence_packet("margin_m2_overlay", margin_m2_rep, "macro", margin_m2_date, max_excerpt_chars=700),
        ai_cio._build_evidence_packet("vnibor", vnibor_rep, "macro", vnibor_date, max_excerpt_chars=1000),
        ai_cio._build_evidence_packet("ltmm", ltmm_rep, "macro", ltmm_date, max_excerpt_chars=2400),
        ai_cio._build_evidence_packet("vn100_corporate_health", vn100_rep, "fundamental", vn100_label, max_excerpt_chars=1200),
        ai_cio._build_evidence_packet("humility_falsification", humility_context, "audit", max_excerpt_chars=900),
        current_packets["fear_greed"],
        current_packets["manipulation"],
        current_packets["dispersion"],
        current_packets["upside_ratio"],
        current_packets["bank_valuation"],
        current_packets["market_breadth"],
        current_packets["esr_monitor"],
        current_packets["va_res"],
        current_packets["var_cvar_vnindex"],
        ai_cio._build_evidence_packet("abm_simulator", abm_rep, "tail_risk", abm_date, max_excerpt_chars=900),
        current_packets["sentiment_factor_news"],
        current_packets["risk_adjusted_growth"],
        ai_cio._build_evidence_packet("pvgo", pvgo_context, "valuation", data_date, max_excerpt_chars=700),
    ]
    capitulation_state = ai_cio._build_capitulation_state(df_stocks, evidence_packets)
    evidence_packets.append(ai_cio._build_capitulation_evidence_packet(capitulation_state))

    decision_state = ai_cio._build_decision_state(
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
        report_date=report_date,
        data_date=data_date,
    )
    decision_state = ai_cio._attach_capitulation_policy(decision_state, capitulation_state)
    metrics_snapshot = ai_cio._build_ai_cio_metrics_snapshot(
        provider_key=provider_key,
        report_date=report_date,
        data_date=data_date,
        decision_state=decision_state,
        evidence_packets=evidence_packets,
        history_ledger=history_ledger,
    )
    all_reports = ai_cio._build_ai_cio_structured_context(
        data_note=data_note,
        historical_block=historical_block,
        evidence_packets=evidence_packets,
        decision_state=decision_state,
        metrics_snapshot=metrics_snapshot,
    )

    master_prompt = (ROOT_DIR / "promt" / "executive_summary_promt.md").read_text(encoding="utf-8")
    master_full = master_prompt.replace("{all_reports}", all_reports)
    parts = master_full.split("# INPUT DATA")
    system_prompt = parts[0].strip()
    user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else master_full

    return {
        "provider": provider_key,
        "model": AI_PROVIDER_MAP[provider_key]["api_model"],
        "temperature": AI_PROVIDER_MAP[provider_key].get("temperature"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_date": report_date,
        "data_date": data_date,
        "cache_policy": "latest cached child-tool reports; no LLM/API calls during export",
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "decision_state": decision_state,
        "evidence_packet_count": len(evidence_packets),
    }


def _default_output_path(provider_key: str) -> Path:
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    today_key = date.today().strftime("%d%m%y")
    return desktop / f"ai_cio_llm_prompt_{provider_key}_{today_key}.md"


def write_prompt_markdown(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    decision_state = payload.get("decision_state") or {}
    metadata = {
        key: payload.get(key)
        for key in (
            "provider",
            "model",
            "temperature",
            "generated_at",
            "report_date",
            "data_date",
            "cache_policy",
            "evidence_packet_count",
        )
    }
    text = f"""# AI CIO LLM Prompt Audit

## Metadata
```json
{json.dumps(metadata, ensure_ascii=False, indent=2, default=str)}
```

## Deterministic Decision State Summary
```json
{json.dumps({
    "metric_implied_score": decision_state.get("metric_implied_score"),
    "metric_implied_regime": decision_state.get("metric_implied_regime"),
    "stress_regime": decision_state.get("stress_regime"),
    "resolved_regime": decision_state.get("resolved_regime"),
    "capitulation_state": decision_state.get("capitulation_state"),
    "allocation_guardrail": decision_state.get("allocation_guardrail"),
    "metric_implied_subscores": decision_state.get("metric_implied_subscores"),
    "hard_constraints": decision_state.get("hard_constraints"),
    "tool_score_count": decision_state.get("tool_score_count"),
    "score_band_reason": decision_state.get("score_band_reason"),
}, ensure_ascii=False, indent=2, default=str)}
```

## System Prompt Sent To LLM
````text
{payload["system_prompt"]}
````

## User Prompt Sent To LLM
````text
{payload["user_prompt"]}
````
"""
    output_path.write_text(text, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the final AI CIO LLM prompt to Markdown without calling the LLM.")
    parser.add_argument("--provider", default="deepseek-v4-pro", choices=sorted(AI_PROVIDER_MAP.keys()))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    payload = build_ai_cio_prompt_payload(args.provider)
    output_path = args.output or _default_output_path(args.provider)
    written = write_prompt_markdown(payload, output_path)
    print(str(written))


if __name__ == "__main__":
    main()
