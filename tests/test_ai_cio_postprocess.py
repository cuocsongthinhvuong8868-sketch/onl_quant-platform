import json
from pathlib import Path
from datetime import date, timedelta

from shared.ai_cio import parse_score_regime, postprocess_executive_summary_report


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
    )
    assert "deepseek-v4-pro" in history_path.read_text(encoding="utf-8")
    assert "kimi-2.6-local" not in history_path.read_text(encoding="utf-8")


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
        {"date": "2026-06-18", "score": "13", "regime": "CRISIS / PRE-CRASH", "provider": "deepseek-v4-pro"},
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

    assert snapshot["metrics_version"] == "2.0"
    assert snapshot["tools"]["market_breadth"]["tool_score"] == 35
    assert snapshot["tools"]["pvgo"]["tool_score"] == 42
    assert snapshot["tools"]["pvgo"]["tool_regime"] == "PVGO ELEVATED EXPECTATION RISK"
    assert snapshot["history"]["window_size"] == ai_cio.AI_CIO_HISTORY_WINDOW
    assert snapshot["history"]["rolling_summary"]["history_count"] == 3
    assert snapshot["history"]["rolling_summary"]["current_baseline_score"] == state["metric_implied_score"]
    assert any(card["tool"] == "pvgo" and "Adapter" in card["authority"] for card in snapshot["methodology_cards"])

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    path = ai_cio._write_ai_cio_metrics_snapshot(snapshot)
    latest = path.parent / "latest.json"
    assert path.name.startswith("metrics_")
    assert latest.exists()
    assert json.loads(latest.read_text(encoding="utf-8"))["tools"]["pvgo"]["tool_score"] == 42


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


def test_tool_score_adapters_are_deterministic():
    from shared.ai_cio_scoring import derive_metric_implied_scores, score_tool_packet

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
    EVT Xi: +0.345
    EVT Xi Min: +0.168
    EVT Xi Max: +0.374
    EVT Xi Range: 0.206
    EVT VaR99 Range: 0.11pp
    EVT ES99 Range: 0.70pp
    EVT Threshold Stable: 0
    """

    packet = ai_cio._build_evidence_packet("var_cvar_vnindex", report, "current_tool")

    assert packet["key_metrics"]["evt_xi"] == 0.345
    assert packet["key_metrics"]["evt_xi_min"] == 0.168
    assert packet["key_metrics"]["evt_xi_max"] == 0.374
    assert packet["key_metrics"]["evt_xi_range"] == 0.206
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


def test_humility_evt_default_uses_sensitivity_upper_bound():
    from tools.humility_falsification import page

    rule = next(item for item in page.DEFAULT_RULES if item["model"] == "Tail Risk (EVT)")

    assert "Xi Max" in rule["metric"]
    assert page._metric_key(rule) == "evt_xi_max"
