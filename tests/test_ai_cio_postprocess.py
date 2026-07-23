import json
from pathlib import Path
from datetime import date, timedelta

from shared.ai_cio import (
    _clean_telegram_summary,
    parse_score_regime,
    postprocess_executive_summary_report,
    strip_wrapping_markdown_fence,
)


def test_parse_score_regime_strict_line():
    text = "final score & regime : 11 ; regime : CRISIS / PRE-CRASH"

    assert parse_score_regime(text) == ("11", "CRISIS / PRE-CRASH")


def test_parse_score_regime_from_summary_fallback():
    text = """# Executive
- **Điểm số tổng hợp (Composite Score)**: 11/100
- **Trạng thái vĩ mô (Regime)**: CRISIS / PRE-CRASH
```json
{"falsification_rules": [
"""

    assert parse_score_regime(text) == ("11", "CRISIS / PRE-CRASH")


def test_strip_wrapping_markdown_fence_preserves_report_body():
    report = (
        "<!-- ai-cio-cache-version: ai_cio_methodology_v3 -->\n"
        "```markdown\n"
        "### EXECUTIVE BOTTOM LINE\n"
        "final score & regime : 29 ; regime : PRE-CRASH / PANIC\n"
        "```\n"
    )

    clean = strip_wrapping_markdown_fence(report)

    assert clean.startswith("<!-- ai-cio-cache-version: ai_cio_methodology_v3 -->")
    assert "```markdown" not in clean
    assert not clean.endswith("```")
    assert "### EXECUTIVE BOTTOM LINE" in clean


def test_postprocess_strips_whole_report_markdown_fence():
    report = (
        "```markdown\n"
        "### EXECUTIVE BOTTOM LINE\n"
        "final score & regime : 29 ; regime : PRE-CRASH / PANIC\n"
        "```\n"
    )

    clean, path = postprocess_executive_summary_report(report, "deepseek-v4-pro")

    assert path is None
    assert clean == (
        "### EXECUTIVE BOTTOM LINE\n"
        "final score & regime : 29 ; regime : PRE-CRASH / PANIC"
    )


def test_postprocess_strips_and_saves_humility_json(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    data_lake = tmp_path / "data_lake"
    monkeypatch.setattr(ai_cio, "DATA_LAKE", data_lake)

    payload = {
        "report_date": "2026-06-05",
        "composite_score": 11,
        "regime": "CRISIS / PRE-CRASH",
        "falsification_rules": [
            {
                "model": "Market Breadth",
                "metric": "Breadth MA20",
                "threshold_operator": ">",
                "threshold_value": 45,
                "current_value": 26.6,
                "unit": "%",
                "description": "Breadth recovery invalidates the thesis.",
            }
        ],
    }
    report = (
        "# Report\n\n"
        "### 8. Model Humility Box\n\n"
        "<!-- HUMILITY_JSON_START -->\n"
        "```json\n"
        f"{json.dumps(payload)}\n"
        "```\n"
        "<!-- HUMILITY_JSON_END -->\n\n"
        "final score & regime : 11 ; regime : CRISIS / PRE-CRASH\n"
    )

    clean, path = postprocess_executive_summary_report(report, "deepseek-v4-pro")

    assert '"falsification_rules"' not in clean
    assert "final score & regime : 11 ; regime : CRISIS / PRE-CRASH" in clean
    assert path == data_lake / "daily_cache" / "ai_cio_humility_rules_deepseek-v4-pro_050626.json"
    assert json.loads(Path(path).read_text(encoding="utf-8"))["falsification_rules"][0]["metric"] == "Breadth MA20"


def test_postprocess_strips_truncated_humility_json_and_restores_final_line(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    report = (
        "# Report\n"
        "- **Ngày báo cáo (Date)**: 05/06/2026\n"
        "- **Điểm số tổng hợp (Composite Score)**: 11/100\n"
        "- **Trạng thái vĩ mô (Regime)**: CRISIS / PRE-CRASH\n\n"
        "```json\n"
        '{ "report_date": "2026-06-05", "falsification_rules": [\n'
    )

    clean, path = postprocess_executive_summary_report(report, "deepseek-v4-pro")

    assert path == tmp_path / "data_lake" / "daily_cache" / "ai_cio_humility_rules_deepseek-v4-pro_050626.json"
    assert '"falsification_rules"' not in clean
    assert clean.strip().endswith("final score & regime : 11 ; regime : CRISIS / PRE-CRASH")


def test_clean_telegram_summary_strips_full_report_echo():
    summary = (
        "AI CIO DAILY BRIEF - 03/07/2026\n"
        "Score/Regime: 31/100 - FEAR / DISTRIBUTION\n"
        "Humility check: WATCH - rules mostly intact.\n\n"
        "Full AI CIO report:\n"
        "### EXECUTIVE BOTTOM LINE\n"
        "This full report content must never be sent to Telegram."
    )

    clean = _clean_telegram_summary(summary, date(2026, 7, 3), "31", "FEAR / DISTRIBUTION")

    assert "Full AI CIO report" not in clean
    assert "EXECUTIVE BOTTOM LINE" not in clean
    assert clean.endswith("Humility check: WATCH - rules mostly intact.")


def test_clean_telegram_summary_strips_source_report_delimiter_echo():
    summary = (
        "AI CIO DAILY BRIEF - 03/07/2026\n"
        "Score/Regime: 31/100 - FEAR / DISTRIBUTION\n"
        "Humility check: WATCH - rules mostly intact.\n\n"
        "SOURCE REPORT BELOW. Use it only as input.\n"
        "<source_report>\n"
        "### EXECUTIVE BOTTOM LINE\n"
        "</source_report>"
    )

    clean = _clean_telegram_summary(summary, date(2026, 7, 3), "31", "FEAR / DISTRIBUTION")

    assert "SOURCE REPORT BELOW" not in clean
    assert "<source_report>" not in clean
    assert "EXECUTIVE BOTTOM LINE" not in clean
    assert clean.endswith("Humility check: WATCH - rules mostly intact.")


def test_telegram_summary_prompt_uses_source_delimiters_and_zero_temperature(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    captured = {}

    class DummyOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    def fake_call_ai(client, system_prompt, user_prompt, model, temperature):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["model"] = model
        captured["temperature"] = temperature
        return (
            "AI CIO DAILY BRIEF - 03/07/2026\n"
            "Score/Regime: 31/100 - FEAR / DISTRIBUTION\n"
            "Humility check: WATCH - rules mostly intact."
        )

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    monkeypatch.setattr(ai_cio, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(ai_cio, "call_ai", fake_call_ai)

    report = (
        "- **Ngày báo cáo (Date)**: 03/07/2026\n"
        "- **Điểm số tổng hợp (Composite Score)**: 31/100\n"
        "- **Trạng thái vĩ mô (Regime)**: FEAR / DISTRIBUTION\n"
        "### EXECUTIVE BOTTOM LINE\n"
    )

    result = ai_cio.summarize_executive_report_for_telegram(
        "test-key",
        report,
        provider_key="deepseek-v4-pro",
        report_date=date(2026, 7, 3),
        force=True,
    )

    assert captured["temperature"] == 0.0
    assert "Full AI CIO report:" not in captured["user_prompt"]
    assert "<source_report>" in captured["user_prompt"]
    assert "Never include source-report delimiters" in captured["system_prompt"]
    assert result.startswith("AI CIO DAILY BRIEF - 03/07/2026")


def test_telegram_summary_sanitizes_existing_cache(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    data_lake = tmp_path / "data_lake"
    cache_dir = data_lake / "daily_cache"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / "telegram_summary_deepseek-v4-pro_030726.txt"
    cache_path.write_text(
        "AI CIO DAILY BRIEF - 03/07/2026\n"
        "Score/Regime: 31/100 - FEAR / DISTRIBUTION\n"
        "Humility check: WATCH - rules mostly intact.\n\n"
        "Full AI CIO report:\n"
        "### EXECUTIVE BOTTOM LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_cio, "DATA_LAKE", data_lake)

    report = (
        "- **Ngày báo cáo (Date)**: 03/07/2026\n"
        "- **Điểm số tổng hợp (Composite Score)**: 31/100\n"
        "- **Trạng thái vĩ mô (Regime)**: FEAR / DISTRIBUTION\n"
    )

    result = ai_cio.summarize_executive_report_for_telegram(
        "unused",
        report,
        provider_key="deepseek-v4-pro",
        report_date=date(2026, 7, 3),
        force=False,
    )

    assert "Full AI CIO report" not in result
    assert "EXECUTIVE BOTTOM LINE" not in result
    assert cache_path.read_text(encoding="utf-8") == result


def test_recent_summaries_uses_compact_ledger_not_raw_reports(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    history_path = data_lake / "Ai_cio_report.csv"
    yesterday = date.today() - timedelta(days=1)
    history_path.write_text(
        "ddmmyyyy,score,regime,source,provider\n"
        f"{yesterday.strftime('%d%m%Y')},42,FEAR / DISTRIBUTION,auto,deepseek-v4-pro\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_cio, "DATA_LAKE", data_lake)
    monkeypatch.setattr(ai_cio, "CSV_HISTORY_PATH", history_path)

    context = ai_cio._read_recent_summaries("deepseek-v4-pro", n_past=7)
    payload = json.loads(context)

    assert payload == [
        {
            "date": yesterday.isoformat(),
            "score": "42",
            "regime": "FEAR / DISTRIBUTION",
            "source": "auto",
            "provider": "deepseek-v4-pro",
        }
    ]
    assert "EXECUTIVE BOTTOM LINE" not in context


def test_recent_summary_cache_fallback_strips_wrapping_markdown_fence(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    data_lake = tmp_path / "data_lake"
    cache_dir = data_lake / "daily_cache"
    cache_dir.mkdir(parents=True)
    yesterday = date.today() - timedelta(days=1)
    cache_path = cache_dir / f"executive_summary_deepseek-v4-pro_{yesterday.strftime('%d%m%y')}.txt"
    cache_path.write_text(
        "<!-- ai-cio-cache-version: ai_cio_methodology_v3 -->\n"
        "```markdown\n"
        "### EXECUTIVE BOTTOM LINE\n"
        "final score & regime : 29 ; regime : PRE-CRASH / PANIC\n"
        "```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_cio, "DATA_LAKE", data_lake)
    monkeypatch.setattr(ai_cio, "CSV_HISTORY_PATH", data_lake / "missing.csv")

    rows = ai_cio._read_recent_summary_ledger("deepseek-v4-pro", n_past=1)

    assert rows[0]["score"] == "29"
    assert rows[0]["regime"] == "PRE-CRASH / PANIC"
    assert "```markdown" not in rows[0]["brief"]


def test_history_csv_only_accepts_deepseek_provider(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    history_path = tmp_path / "Ai_cio_report.csv"
    monkeypatch.setattr(ai_cio, "CSV_HISTORY_PATH", history_path)

    assert not ai_cio.upsert_history_csv(
        "55",
        "NEUTRAL",
        source="manual",
    )
    assert not history_path.exists()

    assert not ai_cio.upsert_history_csv(
        "42",
        "FEAR / DISTRIBUTION",
        source="manual",
        provider="kimi-2.6-local",
    )
    assert not history_path.exists()

    assert ai_cio.upsert_history_csv(
        "24",
        "PRE-CRASH / PANIC",
        source="manual",
        provider="deepseek-v4-pro",
        stress_regime="PRE-CRASH / PANIC",
        capitulation_phase="FRAGILE",
        capitulation_action_eligible=False,
    )
    history_text = history_path.read_text(encoding="utf-8")
    assert "deepseek-v4-pro" in history_text
    assert "kimi-2.6-local" not in history_text
    assert "capitulation_phase" in history_text
    assert "PRE-CRASH / PANIC,FRAGILE,false" in history_text


def test_evidence_packet_compacts_verbose_report_and_extracts_metrics():
    import shared.ai_cio as ai_cio

    verbose = "\n".join(
        [
            "Systemic Stress Index (SSI): 82.5%",
            "Tail Index xi: 0.31",
            "Breadth MA20: 28.4%",
            "Global FCI CQS: 84.0",
            "final score & regime : 22 ; regime : PRE-CRASH / PANIC",
        ]
        + [f"unimportant filler line {idx}" for idx in range(80)]
    )

    packet = ai_cio._build_evidence_packet("risk_test", verbose, "current_tool", max_excerpt_chars=300)

    assert packet["tool"] == "risk_test"
    assert packet["score"] == "22"
    assert packet["regime"] == "PRE-CRASH / PANIC"
    assert packet["key_metrics"]["ssi_pct"] == 82.5
    assert packet["key_metrics"]["evt_xi"] == 0.31
    assert len(packet["evidence_excerpt"]) <= 300


def test_write_ai_cio_context_sidecar(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    metrics_snapshot = {"metrics_version": "1.0", "tools": {"market_breadth": {"tool_score": 35}}}
    path = ai_cio._write_ai_cio_context_sidecar(
        provider_key="test-provider",
        decision_state={"report_date": "20/06/2026", "hard_constraints": ["Breadth MA20 weak"]},
        evidence_packets=[{"tool": "market_breadth", "bias": "bearish"}],
        history_ledger=[{"date": "2026-06-19", "score": "42"}],
        metrics_snapshot=metrics_snapshot,
        metrics_snapshot_path="data_lake/ai_cio_metrics/metrics_200626.json",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name.startswith("ai_cio_context_test-provider_")
    assert payload["provider"] == "test-provider"
    assert payload["decision_state"]["hard_constraints"] == ["Breadth MA20 weak"]
    assert payload["evidence_packets"][0]["tool"] == "market_breadth"
    assert payload["metrics_snapshot_path"].endswith("metrics_200626.json")
    assert payload["metrics_snapshot"]["tools"]["market_breadth"]["tool_score"] == 35


def test_ai_cio_metrics_snapshot_contains_adapter_history_and_methodology(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    packets = [
        {
            "tool": "market_breadth",
            "layer": "current_tool",
            "bias": "neutral_or_mixed",
            "date": "19/06/2026",
            "key_metrics": {"breadth_ma20_pct": 39.8},
        },
        {
            "tool": "pvgo",
            "layer": "valuation",
            "bias": "neutral_or_mixed",
            "date": "19/06/2026",
            "key_metrics": {"pvgo_pct": 46.9, "pe": 14.2, "coe_pct": 14.0},
        },
    ]
    history = [
        {"date": "2026-06-16", "score": "11", "regime": "CRISIS / PRE-CRASH", "provider": "deepseek-v4-pro"},
        {"date": "2026-06-17", "score": "11", "regime": "CRISIS / PRE-CRASH", "provider": "deepseek-v4-pro"},
        {
            "date": "2026-06-18",
            "score": "13",
            "regime": "CRISIS / PRE-CRASH",
            "provider": "deepseek-v4-pro",
            "stress_regime": "EXTREME CRISIS",
            "capitulation_phase": "FRAGILE",
            "capitulation_action_eligible": "false",
        },
    ]
    state = ai_cio._build_decision_state(packets, history, "20/06/2026", "19/06/2026")

    snapshot = ai_cio._build_ai_cio_metrics_snapshot(
        provider_key="deepseek-v4-pro",
        report_date="20/06/2026",
        data_date="19/06/2026",
        decision_state=state,
        evidence_packets=packets,
        history_ledger=history,
    )

    assert snapshot["metrics_version"] == "3.0"
    assert snapshot["tools"]["market_breadth"]["tool_score"] == 35
    assert snapshot["tools"]["pvgo"]["tool_score"] == 42
    assert snapshot["tools"]["pvgo"]["tool_regime"] == "PVGO ELEVATED EXPECTATION RISK"
    assert snapshot["history"]["window_size"] == ai_cio.AI_CIO_HISTORY_WINDOW
    assert snapshot["history"]["rolling_summary"]["history_count"] == 3
    assert snapshot["history"]["rolling_summary"]["current_baseline_score"] == state["metric_implied_score"]
    assert snapshot["history"]["history_window"][-1]["stress_regime"] == "EXTREME CRISIS"
    assert snapshot["history"]["history_window"][-1]["capitulation_phase"] == "FRAGILE"
    assert snapshot["history"]["history_window"][-1]["capitulation_action_eligible"] is False
    assert any(card["tool"] == "pvgo" and "Adapter" in card["authority"] for card in snapshot["methodology_cards"])

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    path = ai_cio._write_ai_cio_metrics_snapshot(snapshot)
    latest = path.parent / "latest.json"
    provider_latest = path.parent / "latest_deepseek-v4-pro.json"
    assert "deepseek-v4-pro" in path.name
    assert path.name.startswith("metrics_")
    assert latest.exists()
    assert provider_latest.exists()
    assert json.loads(latest.read_text(encoding="utf-8"))["tools"]["pvgo"]["tool_score"] == 42


def test_provider_metrics_file_selection_does_not_leak_other_provider(tmp_path):
    import shared.ai_cio as ai_cio

    metrics_dir = tmp_path / ai_cio.AI_CIO_METRICS_DIRNAME
    metrics_dir.mkdir()
    selected = metrics_dir / "metrics_alpha_200726.json"
    selected_alias = metrics_dir / "latest.json"
    other = metrics_dir / "metrics_beta_200726.json"
    malformed = metrics_dir / "broken.json"
    selected.write_text(json.dumps({"provider": "alpha"}), encoding="utf-8")
    selected_alias.write_text(json.dumps({"provider": "alpha"}), encoding="utf-8")
    other.write_text(json.dumps({"provider": "beta"}), encoding="utf-8")
    malformed.write_text("{", encoding="utf-8")

    files = ai_cio._provider_metrics_files(tmp_path, "alpha")

    assert files == sorted([selected, selected_alias])


def test_ai_cio_prompt_and_methodology_discount_mozyfin_social():
    import shared.ai_cio as ai_cio

    card = ai_cio.TOOL_METHODOLOGY_CARDS["sentiment_factor_news"]
    master_prompt = Path("promt/executive_summary_promt.md").read_text(encoding="utf-8")

    assert ai_cio.AI_CIO_TOOL_CACHE_VERSIONS["executive_summary"] == "ai_cio_methodology_v6_updated_tool_prompt_discipline"
    assert ai_cio.AI_CIO_TOOL_CACHE_VERSIONS["sentiment_factor_news"] == "weighted_bayesian_posterior_social_overlay_v2"
    assert "mozyfin_social" in card["limits"]
    assert "source_counts" in card["authority"]
    assert "mozyfin_social" in master_prompt
    assert "lower-confidence social/opinion" in master_prompt
    assert "UPDATED TOOL METHOD DISCIPLINE" in master_prompt
    assert "Manipulation v2" in master_prompt
    assert "PVGO Valuation" in master_prompt


def test_telegram_summary_reads_structured_ai_cio_context(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    data_lake = tmp_path / "data_lake"
    cache_dir = data_lake / "daily_cache"
    cache_dir.mkdir(parents=True)
    target_date = date.today()
    context_path = cache_dir / f"ai_cio_context_deepseek-v4-pro_{target_date.strftime('%d%m%y')}.json"
    context_path.write_text(
        json.dumps(
            {
                "decision_state": {
                    "metric_implied_score": 27,
                    "metric_implied_regime": "PRE-CRASH / PANIC",
                    "metric_implied_subscores": {"tail_risk_score": 18},
                    "tool_score_count": 2,
                    "tool_scores": [
                        {"tool": "var_cvar_vnindex", "tool_score": 18, "tool_regime": "CRISIS / PRE-CRASH"},
                        {"tool": "market_breadth", "tool_score": 35, "tool_regime": "FEAR / DISTRIBUTION"},
                    ],
                    "hard_constraints": ["EVT xi elevated at 0.345"],
                    "score_band_reason": "Tail risk caps score in PRE-CRASH band.",
                    "previous_cio_diagnostic": {"score_delta_from_metric_implied": 14},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    metrics_dir = data_lake / "ai_cio_metrics"
    metrics_dir.mkdir(parents=True)
    metrics_path = metrics_dir / f"metrics_{target_date.strftime('%d%m%y')}.json"
    metrics_path.write_text(
        json.dumps(
            {
                "history": {
                    "rolling_summary": {
                        "score_avg_5d": 18.4,
                        "days_below_30": 8,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_cio, "DATA_LAKE", data_lake)

    context = ai_cio._read_ai_cio_context_for_summary("deepseek-v4-pro", target_date)
    payload = json.loads(context)

    assert payload["metric_implied_score"] == 27
    assert payload["metric_implied_regime"] == "PRE-CRASH / PANIC"
    assert payload["tool_score_count"] == 2
    assert payload["tool_scores"][0]["tool"] == "var_cvar_vnindex"
    assert payload["hard_constraints"] == ["EVT xi elevated at 0.345"]
    assert payload["history_rolling_summary"]["days_below_30"] == 8
    assert payload["metrics_snapshot_path"].endswith(metrics_path.name)


def test_decision_state_metric_score_resists_prior_score_anchoring():
    import shared.ai_cio as ai_cio

    packets = [
        {
            "tool": "market_breadth",
            "layer": "current_tool",
            "bias": "neutral_or_mixed",
            "key_metrics": {"breadth_ma20_pct": 39.8},
        },
        {
            "tool": "esr_monitor",
            "layer": "current_tool",
            "bias": "bearish",
            "key_metrics": {"ssi_pct": 65.8},
        },
        {
            "tool": "var_cvar_vnindex",
            "layer": "current_tool",
            "bias": "neutral_or_mixed",
            "key_metrics": {"evt_xi": 0.345},
        },
        {
            "tool": "sentiment_factor_news",
            "layer": "current_tool",
            "bias": "bullish",
            "key_metrics": {},
        },
    ]
    history = [{"date": "2026-06-18", "score": "13", "regime": "CRISIS / PRE-CRASH"}]

    state = ai_cio._build_decision_state(packets, history, "20/06/2026", "19/06/2026")

    assert state["metric_implied_regime"] == "PRE-CRASH / PANIC"
    assert 15 <= state["metric_implied_score"] <= 29
    assert state["tool_score_count"] == 3
    assert {item["tool"] for item in state["tool_scores"]} == {
        "market_breadth",
        "esr_monitor",
        "var_cvar_vnindex",
    }
    hard_bearish = state["consensus_map"]["hard_adapter_consensus"]["bearish"]
    soft_bullish = state["consensus_map"]["soft_interpretive_consensus"]["bullish"]
    assert {item["tool"] for item in hard_bearish} == {
        "market_breadth",
        "esr_monitor",
        "var_cvar_vnindex",
    }
    assert [item["tool"] for item in soft_bullish] == ["sentiment_factor_news"]
    assert state["previous_cio_diagnostic"]["score_delta_from_metric_implied"] is not None
    assert "Diagnostic only" in state["previous_cio_diagnostic"]["use_rule"]


def test_final_score_drift_audit_flags_large_llm_overlay_without_overriding():
    import shared.ai_cio as ai_cio

    report = (
        "### 5.5 LLM Overlay\n"
        "- Metric-implied score/regime: 27/100, PRE-CRASH / PANIC\n"
        "- Overlay adjustment: negative, -13 points\n"
        "- Final CIO score after overlay: 14/100\n\n"
        "final score & regime : 14 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "metric_implied_score": 27,
        "metric_implied_regime": "PRE-CRASH / PANIC",
    }

    audited = ai_cio._annotate_final_score_drift(report, decision_state)

    assert "Final Score Drift Audit" in audited
    assert "large overlay drift -13 points" in audited
    assert audited.strip().endswith("final score & regime : 14 ; regime : PRE-CRASH / PANIC")
    assert ai_cio.parse_score_regime(audited) == ("14", "PRE-CRASH / PANIC")


def test_final_score_drift_audit_allows_small_same_band_overlay():
    import shared.ai_cio as ai_cio

    report = (
        "- Metric-implied score/regime: 27/100, PRE-CRASH / PANIC\n"
        "- Overlay adjustment: negative, -3 points\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "metric_implied_score": 27,
        "metric_implied_regime": "PRE-CRASH / PANIC",
    }

    audited = ai_cio._annotate_final_score_drift(report, decision_state)

    assert "Final Score Drift Audit" not in audited
    assert ai_cio.parse_score_regime(audited) == ("24", "PRE-CRASH / PANIC")


def test_final_regime_enforcement_rejects_unconfirmed_capitulation():
    import shared.ai_cio as ai_cio

    report = (
        "final score & regime : 90 ; regime : EXTREME GREED / TOP WARNING\n"
        "**final score & regime : 7 ; regime : CAPITULATION**"
    )
    decision_state = {
        "capitulation_state": {
            "phase": "CAPITULATION_CLIMAX",
            "action_eligible": True,
            "data_quality": {"status": "GOOD"},
        }
    }

    enforced = ai_cio._enforce_final_score_regime(report, decision_state)

    assert "final score & regime : 90" not in enforced
    assert enforced.endswith("**final score & regime : 7 ; regime : EXTREME CRISIS**")
    assert ai_cio.parse_score_regime(enforced) == ("7", "EXTREME CRISIS")


def test_final_regime_enforcement_allows_only_actionable_exhaustion():
    import shared.ai_cio as ai_cio

    report = "final score & regime : 12 ; regime : EXTREME CRISIS"
    eligible_state = {
        "capitulation_state": {
            "phase": "EXHAUSTION_CONFIRMED",
            "action_eligible": True,
            "data_quality": {"status": "LIMITED"},
            "freshness_status": "CURRENT",
        }
    }
    insufficient_state = {
        "capitulation_state": {
            "phase": "EXHAUSTION_CONFIRMED",
            "action_eligible": True,
            "data_quality": {"status": "INSUFFICIENT"},
            "freshness_status": "CURRENT",
        }
    }

    eligible = ai_cio._enforce_final_score_regime(report, eligible_state)
    insufficient = ai_cio._enforce_final_score_regime(
        eligible,
        insufficient_state,
    )

    assert ai_cio.parse_score_regime(eligible) == ("12", "CAPITULATION")
    assert ai_cio.parse_score_regime(insufficient) == ("12", "EXTREME CRISIS")


def test_capitulation_policy_fails_closed_on_bad_quality_or_stale_data():
    import shared.ai_cio as ai_cio

    base_state = {
        "phase": "EXHAUSTION_CONFIRMED",
        "action_eligible": True,
        "data_quality": {"status": "GOOD"},
        "freshness_status": "CURRENT",
    }
    insufficient = {**base_state, "data_quality": {"status": "INSUFFICIENT"}}
    stale = {**base_state, "freshness_status": "STALE"}
    missing_flag = {key: value for key, value in base_state.items() if key != "action_eligible"}
    missing_freshness = {
        key: value for key, value in base_state.items() if key != "freshness_status"
    }

    assert ai_cio._capitulation_action_eligible({"capitulation_state": base_state}) is True
    assert ai_cio._capitulation_action_eligible({"capitulation_state": insufficient}) is False
    assert ai_cio._capitulation_action_eligible({"capitulation_state": stale}) is False
    assert ai_cio._capitulation_action_eligible({"capitulation_state": missing_flag}) is False
    assert ai_cio._capitulation_action_eligible({"capitulation_state": missing_freshness}) is False


def test_allocation_guard_clamps_false_capitulation_body_and_keeps_final_line_last():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **80%**\n"
        "- **Equity**: **20%**, buy the capitulation bottom.\n"
        "- **Short VN30F1M**: **0%**.\n\n"
        "final score & regime : 7 ; regime : CAPITULATION"
    )
    decision_state = {
        "capitulation_state": {
            "phase": "CAPITULATION_CLIMAX",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        }
    }

    enforced = ai_cio._enforce_final_score_regime(report, decision_state)
    enforced = ai_cio._enforce_final_allocation_policy(enforced, decision_state)

    assert "- **Cash**: **100%**" in enforced
    assert "- **Equity**: **0%**" in enforced
    assert "Deterministic Allocation Guardrail" in enforced
    assert "Any conflicting allocation or bottom-fishing instruction above is void" in enforced
    assert enforced.strip().endswith(
        "final score & regime : 7 ; regime : EXTREME CRISIS"
    )


def test_allocation_guard_closes_short_only_for_confirmed_exhaustion_override():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **80%**\n"
        "- **Equity**: **20%**\n"
        "- **Short VN30F1M**: **10%**\n\n"
        "final score & regime : 12 ; regime : EXTREME CRISIS"
    )
    decision_state = {
        "capitulation_state": {
            "phase": "EXHAUSTION_CONFIRMED",
            "action_eligible": True,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        }
    }

    enforced = ai_cio._enforce_final_score_regime(report, decision_state)
    enforced = ai_cio._enforce_final_allocation_policy(enforced, decision_state)

    assert "- **Equity**: **20%**" in enforced
    assert "- **Short VN30F1M**: **0%**" in enforced
    assert enforced.strip().endswith("final score & regime : 12 ; regime : CAPITULATION")


def test_llm_overlay_cannot_widen_deterministic_baseline_allocation_cap():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **70%**\n"
        "- **Equity**: **30%**\n"
        "- **Short VN30F1M**: **0%**\n\n"
        "final score & regime : 31 ; regime : FEAR / DISTRIBUTION"
    )
    decision_state = {
        "allocation_guardrail": {
            "max_equity_pct": 15.0,
            "max_short_vn30f1m_pct": 0.0,
        },
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)

    assert "- **Cash**: **85%**" in enforced
    assert "- **Equity**: **15%**" in enforced
    assert "deterministic baseline cap" in enforced


def test_incomplete_or_range_allocation_gets_safe_normalized_order():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- Cash 85-95% | Equity 5-15%\n"
        "- Short Hedge: KHÔNG\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "allocation_guardrail": {
            "max_equity_pct": 15.0,
            "max_short_vn30f1m_pct": 0.0,
        },
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)

    assert "**Deterministic Normalized Executive Order**" in enforced
    assert "- **Cash**: **100%**" in enforced
    assert "- **Equity**: **0%**" in enforced
    assert "- **Short VN30F1M**: **0%**" in enforced
    assert enforced.strip().endswith(
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )


def test_missing_executive_order_fails_closed_with_normalized_zero_risk_block():
    import shared.ai_cio as ai_cio

    report = (
        "### Executive Bottom Line\n"
        "The model proposes an unstructured allocation.\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "allocation_guardrail": {
            "max_equity_pct": 15.0,
            "max_short_vn30f1m_pct": 0.0,
        },
        "capitulation_state": {
            "phase": "FRAGILE",
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
            "action_eligible": False,
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)

    assert "### 6. Deterministic Executive Order" in enforced
    assert "- **Cash**: **100%**" in enforced
    assert "- **Equity**: **0%**" in enforced
    assert enforced.strip().endswith(
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )


def test_allocation_guard_validates_last_repeated_order_used_by_pdf():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **100%**\n"
        "- **Equity**: **0%**\n"
        "- **Short VN30F1M**: **0%**\n\n"
        "The following repeated block must not bypass policy:\n"
        "- **Cash**: **70%**\n"
        "- **Equity**: **30%**\n"
        "- **Short VN30F1M**: **10%**\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "allocation_guardrail": {
            "max_equity_pct": 15.0,
            "max_short_vn30f1m_pct": 0.0,
        },
        "capitulation_state": {
            "phase": "FRAGILE",
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
            "action_eligible": False,
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)

    assert enforced.count("- **Cash**: **85%**") == 1
    assert enforced.count("- **Equity**: **15%**") == 1
    assert enforced.count("- **Short VN30F1M**: **0%**") == 2


def test_post_final_duplicate_order_cannot_bypass_enforcer_or_pdf_parser():
    import shared.ai_cio as ai_cio
    from shared.pdf_export import _extract_executive_order

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **85%**\n"
        "- **Equity**: **15%**\n"
        "- **Short VN30F1M**: **0%**\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC\n\n"
        "- **Cash**: **20%**\n"
        "- **Equity**: **80%**\n"
        "- **Short VN30F1M**: **10%**"
    )
    decision_state = {
        "metric_implied_score": 24,
        "metric_implied_regime": "PRE-CRASH / PANIC",
        "allocation_guardrail": {
            "max_equity_pct": 15.0,
            "max_short_vn30f1m_pct": 0.0,
        },
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)
    orders = {item["sleeve"]: item["target"] for item in _extract_executive_order(enforced)}

    assert enforced.strip().endswith(
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    assert "- **Equity**: **80%**" not in enforced
    assert orders["Equity"] == "15%"
    assert orders["Short VN30F1M"] == "0%"


def test_section_seven_sleeves_do_not_hide_unsafe_section_six_order():
    import shared.ai_cio as ai_cio
    from shared.pdf_export import _extract_executive_order

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **20%**\n"
        "- **Equity**: **80%**\n"
        "- **Short VN30F1M**: **10%**\n\n"
        "### 7. Confidence Note\n"
        "- **Cash**: **100%**\n"
        "- **Equity**: **0%**\n"
        "- **Short VN30F1M**: **0%**\n\n"
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )
    decision_state = {
        "metric_implied_score": 24,
        "metric_implied_regime": "PRE-CRASH / PANIC",
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)
    orders = {item["sleeve"]: item["target"] for item in _extract_executive_order(enforced)}

    assert orders["Cash"] == "85%"
    assert orders["Equity"] == "15%"
    assert orders["Short VN30F1M"] == "0%"


def test_initial_allocation_guardrail_applies_ssi_and_robust_evt_caps():
    import shared.ai_cio as ai_cio

    base = {
        "metric_implied_score": 85,
        "metric_implied_regime": "BULL CONFIRMED",
        "score_band_reason": {},
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }
    low_ssi = ai_cio._allocation_policy_for_score(
        85,
        {**base, "metric_values": {"esr_monitor.ssi_pct": 0.9}},
    )
    elevated_ssi = ai_cio._allocation_policy_for_score(
        85,
        {**base, "metric_values": {"esr_monitor.ssi_pct": 63}},
    )
    critical_ssi = ai_cio._attach_capitulation_policy(
        {**base, "metric_values": {"esr_monitor.ssi_pct": 81}},
        base["capitulation_state"],
    )["allocation_guardrail"]
    robust_evt = ai_cio._allocation_policy_for_score(
        85,
        {
            **base,
            "metric_values": {
                "var_cvar_vnindex.evt_xi": 0.31,
                "var_cvar_vnindex.evt_xi_min": 0.30,
            },
        },
    )

    assert low_ssi["max_equity_pct"] == 95
    assert elevated_ssi["max_equity_pct"] == 90
    assert critical_ssi["max_equity_pct"] == 30
    assert critical_ssi["min_cash_pct"] == 70
    assert robust_evt["max_equity_pct"] == 30
    assert robust_evt["min_cash_pct"] == 70


def test_allocation_guard_reads_bold_low_confidence_and_reduces_one_bracket():
    import shared.ai_cio as ai_cio

    for confidence_line in (
        "- **Final confidence**: **LOW**",
        "Final confidence: **LOW**",
    ):
        report = (
            "### 6. Executive Order\n"
            "- **Cash**: **25%**\n"
            "- **Equity**: **75%**\n"
            "- **Short VN30F1M**: **0%**\n\n"
            f"### 7. Confidence Note\n{confidence_line}\n\n"
            "final score & regime : 65 ; regime : UPTREND / EXPANSION"
        )

        enforced = ai_cio._enforce_final_allocation_policy(report, {})

        assert "- **Cash**: **45%**" in enforced
        assert "- **Equity**: **55%**" in enforced
        assert "LOW-confidence one-bracket reduction" in enforced


def test_allocation_guard_uses_deterministic_score_when_final_line_is_missing():
    import shared.ai_cio as ai_cio

    report = (
        "### 6. Executive Order\n"
        "- **Cash**: **5%**\n"
        "- **Equity**: **95%**\n"
        "- **Short VN30F1M**: **0%**"
    )
    decision_state = {
        "metric_implied_score": 24,
        "metric_implied_regime": "PRE-CRASH / PANIC",
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_allocation_policy(report, decision_state)

    assert "- **Cash**: **85%**" in enforced
    assert "- **Equity**: **15%**" in enforced
    assert enforced.strip().endswith(
        "final score & regime : 24 ; regime : PRE-CRASH / PANIC"
    )


def test_final_regime_enforcement_clamps_score_bounds_and_structured_label():
    import shared.ai_cio as ai_cio

    below = ai_cio._enforce_final_score_regime(
        "- **Resolved Regime**: CAPITULATION\n\n"
        "final score & regime : -10 ; regime : CAPITULATION",
        {},
    )
    above = ai_cio._enforce_final_score_regime(
        "final score & regime : 150 ; regime : CAPITULATION",
        {},
    )

    assert ai_cio.parse_score_regime(below) == ("0", "EXTREME CRISIS")
    assert "- **Resolved Regime**: EXTREME CRISIS" in below
    assert ai_cio.parse_score_regime(above) == (
        "100",
        "EXTREME GREED / TOP WARNING",
    )


def test_postprocess_normalizes_humility_sidecar_to_enforced_regime(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    payload = {
        "report_date": "2026-07-20",
        "composite_score": 7,
        "regime": "CAPITULATION",
        "falsification_rules": [],
    }
    report = (
        "<!-- HUMILITY_JSON_START -->\n"
        "```json\n"
        f"{json.dumps(payload)}\n"
        "```\n"
        "<!-- HUMILITY_JSON_END -->\n\n"
        "final score & regime : 7 ; regime : CAPITULATION"
    )
    decision_state = {
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        }
    }

    clean, path = ai_cio.postprocess_executive_summary_report(
        report,
        "chatgpt-local",
        decision_state=decision_state,
    )
    sidecar = json.loads(path.read_text(encoding="utf-8"))

    assert ai_cio.parse_score_regime(clean) == ("7", "EXTREME CRISIS")
    assert sidecar["regime"] == "EXTREME CRISIS"


def test_postprocess_normalizes_payload_only_regime_before_writing_sidecar(
    tmp_path,
    monkeypatch,
):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    payload = {
        "report_date": "2026-07-20",
        "composite_score": 7,
        "regime": "CAPITULATION",
        "falsification_rules": [],
    }
    report = (
        "<!-- HUMILITY_JSON_START -->\n"
        "```json\n"
        f"{json.dumps(payload)}\n"
        "```\n"
        "<!-- HUMILITY_JSON_END -->"
    )
    decision_state = {
        "capitulation_state": {
            "phase": "FRAGILE",
            "action_eligible": False,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        }
    }

    clean, path = ai_cio.postprocess_executive_summary_report(
        report,
        "chatgpt-local",
        decision_state=decision_state,
    )
    sidecar = json.loads(path.read_text(encoding="utf-8"))

    assert ai_cio.parse_score_regime(clean) == ("7", "EXTREME CRISIS")
    assert sidecar["regime"] == "EXTREME CRISIS"


def test_drift_audit_accepts_actionable_capitulation_override():
    import shared.ai_cio as ai_cio

    report = "final score & regime : 12 ; regime : EXTREME CRISIS"
    decision_state = {
        "metric_implied_score": 12,
        "metric_implied_regime": "EXTREME CRISIS",
        "capitulation_state": {
            "phase": "EXHAUSTION_CONFIRMED",
            "action_eligible": True,
            "data_quality": {"status": "GOOD"},
            "freshness_status": "CURRENT",
        },
    }

    enforced = ai_cio._enforce_final_score_regime(report, decision_state)
    audited = ai_cio._annotate_final_score_drift(enforced, decision_state)

    assert ai_cio.parse_score_regime(audited) == ("12", "CAPITULATION")
    assert "Final Score Drift Audit" not in audited


def test_final_regime_enforcement_matches_non_capitulation_score_band():
    import shared.ai_cio as ai_cio

    report = "final score & regime : 14 ; regime : PRE-CRASH / PANIC"

    enforced = ai_cio._enforce_final_score_regime(report, {})

    assert enforced == "final score & regime : 14 ; regime : EXTREME CRISIS"
    assert ai_cio._score_band_for_regime("CAPITULATION") is None
    assert ai_cio._score_band_for_regime("EXTREME CRISIS") == (0, 14)


def test_tool_score_adapters_are_deterministic():
    from shared.ai_cio_scoring import derive_metric_implied_scores, regime_from_score, score_tool_packet

    # The score is monotonic health/stress. Capitulation requires an independent
    # price-phase confirmation and is never inferred from a low scalar score.
    assert regime_from_score(0) == "EXTREME CRISIS"
    assert regime_from_score(7) == "EXTREME CRISIS"
    assert regime_from_score(14) == "EXTREME CRISIS"

    breadth = score_tool_packet("market_breadth", {"breadth_ma20_pct": 39.8})
    esr = score_tool_packet("esr_monitor", {"ssi_pct": 65.8})
    tail = score_tool_packet("var_cvar_vnindex", {"evt_xi": 0.345})

    assert breadth["tool_score"] == 35
    assert esr["tool_score"] == 35
    assert tail["tool_score"] == 18

    aggregate = derive_metric_implied_scores(
        {
            "market_breadth.breadth_ma20_pct": 39.8,
            "esr_monitor.ssi_pct": 65.8,
            "var_cvar_vnindex.evt_xi": 0.345,
        },
        {"bullish": 0, "bearish": 1, "neutral_or_mixed": 2},
        tool_scores=[{"tool": "market_breadth", **breadth}, {"tool": "esr_monitor", **esr}, {"tool": "var_cvar_vnindex", **tail}],
    )

    assert aggregate["metric_implied_regime"] == "PRE-CRASH / PANIC"
    assert 15 <= aggregate["metric_implied_score"] <= 29


def test_evt_threshold_sensitive_xi_does_not_trigger_standalone_precrash_cap():
    from shared.ai_cio_scoring import derive_metric_implied_scores, score_tool_packet

    metrics = {
        "evt_xi": 0.345,
        "evt_xi_min": 0.168,
        "evt_xi_max": 0.374,
        "evt_xi_range": 0.206,
        "evt_threshold_stable": 0,
    }
    tail = score_tool_packet("var_cvar_vnindex", metrics)

    assert tail["tool_score"] == 35
    assert "threshold-sensitive" in tail["score_reason"]

    aggregate = derive_metric_implied_scores(
        {f"var_cvar_vnindex.{key}": value for key, value in metrics.items()},
        {"bullish": 0, "bearish": 1, "neutral_or_mixed": 0},
        tool_scores=[{"tool": "var_cvar_vnindex", **tail}],
    )

    assert not any("PRE-CRASH cap: EVT" in reason for reason in aggregate["score_band_reason"]["caps"])
    assert any("No EVT hard cap" in reason for reason in aggregate["score_band_reason"]["caps"])


def test_evt_robust_fat_tail_preserves_precrash_cap():
    from shared.ai_cio_scoring import derive_metric_implied_scores, score_tool_packet

    metrics = {
        "evt_xi": 0.345,
        "evt_xi_min": 0.312,
        "evt_xi_max": 0.374,
        "evt_xi_range": 0.062,
        "evt_threshold_stable": 1,
    }
    tail = score_tool_packet("var_cvar_vnindex", metrics)

    assert tail["tool_score"] == 18
    aggregate = derive_metric_implied_scores(
        {f"var_cvar_vnindex.{key}": value for key, value in metrics.items()},
        {"bullish": 0, "bearish": 1, "neutral_or_mixed": 0},
        tool_scores=[{"tool": "var_cvar_vnindex", **tail}],
    )

    assert aggregate["metric_implied_score"] <= 29
    assert any("robustly >=0.30" in reason for reason in aggregate["score_band_reason"]["caps"])


def test_evidence_packet_extracts_evt_sensitivity_metrics():
    import shared.ai_cio as ai_cio

    report = """
    EVT Xi MLE: +0.345
    EVT Xi Min: +0.168
    EVT Xi Max: +0.374
    EVT Xi Range: 0.206
    EVT Xi P05: +0.201
    EVT Xi P50: +0.423
    EVT Xi P95: +0.651
    EVT VaR99 Range: 0.11pp
    EVT ES99 Range: 0.70pp
    EVT Threshold Stable: 0
    """

    packet = ai_cio._build_evidence_packet("var_cvar_vnindex", report, "current_tool")

    assert packet["key_metrics"]["evt_xi"] == 0.345
    assert packet["key_metrics"]["evt_xi_min"] == 0.168
    assert packet["key_metrics"]["evt_xi_max"] == 0.374
    assert packet["key_metrics"]["evt_xi_range"] == 0.206
    assert packet["key_metrics"]["evt_xi_p05"] == 0.201
    assert packet["key_metrics"]["evt_xi_p50"] == 0.423
    assert packet["key_metrics"]["evt_xi_p95"] == 0.651
    assert packet["key_metrics"]["evt_threshold_stable"] == 0
    assert packet["adapter_score"]["tool_score"] == 35


def test_methodology_versioned_cache_rejects_legacy_content(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    path = ai_cio._get_cache_path("var_cvar_vnindex", "test-provider")
    path.parent.mkdir(parents=True)
    path.write_text("legacy report without methodology marker", encoding="utf-8")

    assert ai_cio._read_cache("var_cvar_vnindex", "test-provider") is None

    ai_cio._write_cache("var_cvar_vnindex", "current report", "test-provider")
    raw = path.read_text(encoding="utf-8")
    assert ai_cio.AI_CIO_TOOL_CACHE_VERSIONS["var_cvar_vnindex"] in raw
    assert ai_cio._read_cache("var_cvar_vnindex", "test-provider") == "current report"


def test_executive_summary_cache_read_strips_wrapping_markdown_fence(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")

    ai_cio._write_cache(
        "executive_summary",
        "```markdown\n# Report\nfinal score & regime : 29 ; regime : PRE-CRASH / PANIC\n```\n",
        "test-provider",
    )

    assert ai_cio._read_cache("executive_summary", "test-provider") == (
        "# Report\nfinal score & regime : 29 ; regime : PRE-CRASH / PANIC"
    )


def test_humility_evt_default_uses_sensitivity_upper_bound():
    from tools.humility_falsification import page

    rule = next(item for item in page.DEFAULT_RULES if item["model"] == "Tail Risk (EVT)")

    assert "Xi Max" in rule["metric"]
    assert page._metric_key(rule) == "evt_xi_max"
