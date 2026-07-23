from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.ai_cio_chat import ProjectDataCatalog
from shared.ai_cio_data_agent import (
    DATA_AGENT_VERSION,
    MAX_TOOL_RESULT_CHARS,
    DataAgentToolbox,
    _bounded_tool_content,
    ask_ai_cio_data_agent,
    available_provider_keys,
    is_local_provider,
)


def _catalog(tmp_path: Path) -> ProjectDataCatalog:
    for directory in ("data_lake", "reports", "docs", "config"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    return ProjectDataCatalog(
        root_dir=tmp_path,
        data_roots=("data_lake", "reports", "docs", "config"),
        root_files=(),
        use_manifest=False,
    )


class _SequencedCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=outcome)])


class _FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.completions = _SequencedCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)


def _tool_call_message(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
            )
        ],
    )


def _write_systemic_risk_snapshot(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "data_lake/ai_cio_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-07-23T07:15:48Z",
        "report_date": "23/07/2026",
        "data_date": "22/07/2026",
        "score_anchor": {
            "metric_implied_score": 25,
            "metric_implied_regime": "PRE-CRASH / PANIC",
            "stress_regime": "PRE-CRASH / PANIC",
            "resolved_regime": "PRE-CRASH / PANIC",
            "capitulation_override_active": False,
            "metric_implied_subscores": {
                "macro_risk_score": 15,
                "market_internal_score": 13,
                "tail_risk_score": 35,
            },
            "hard_constraints": ["Breadth MA20 weak at 6.1%", "Global FCI CQS high at 99.9"],
            "capitulation_state": {
                "as_of": "2026-07-22T00:00:00",
                "phase": "FRAGILE",
                "stress_risk_score_uncalibrated": 61.4,
                "liquidation_risk_score_uncalibrated": 68.5,
                "features": {
                    "return_1d": -0.0358,
                    "return_3d": -0.0665,
                    "breadth_ma20": 0.061,
                    "esr_ssi": 0.633,
                },
                "freshness_status": "CURRENT",
            },
        },
        "consensus": {
            "hard_adapter_consensus": {
                "bullish": [],
                "bearish": [
                    {
                        "tool": "market_breadth",
                        "tool_score": 18,
                        "tool_regime": "PRE-CRASH / PANIC",
                        "reason": "Breadth MA20 <25% (6.1%)",
                    },
                    {
                        "tool": "global_financial_conditions",
                        "tool_score": 20,
                        "tool_regime": "PRE-CRASH / PANIC",
                        "reason": "CQS >=85 (99.9)",
                    },
                ],
                "neutral_or_mixed": [],
            }
        },
        "final_output": {
            "score": 25.0,
            "stress_regime": "PRE-CRASH / PANIC",
            "resolved_regime": "PRE-CRASH / PANIC",
            "confidence": "medium",
        },
        "tools": {
            "market_breadth": {
                "as_of": "22/07/2026",
                "tool_score": 18,
                "tool_regime": "PRE-CRASH / PANIC",
                "tool_bias": "bearish",
                "data_quality": "structured_adapter",
                "score_reason": "Breadth MA20 <25% (6.1%)",
                "key_metrics": {"breadth_ma20_pct": 6.1},
            },
            "esr_monitor": {
                "as_of": "22/07/2026",
                "tool_score": 42,
                "tool_regime": "FEAR / DISTRIBUTION",
                "tool_bias": "neutral_or_mixed",
                "data_quality": "structured_adapter",
                "score_reason": "SSI >=55% (63.3%)",
                "key_metrics": {"ssi_pct": 63.3},
            },
        },
    }
    (metrics_dir / "latest_chatgpt-local.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_data_agent_executes_timeseries_tool_and_returns_displays(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/vnindex_cache.csv").write_text(
        "time,VNINDEX,VNINDEX_volume\n"
        "2026-07-20,1743.51,862568937\n"
        "2026-07-22,1668.53,915046404\n"
        "2026-07-21,1730.56,789069211\n",
        encoding="utf-8",
    )
    catalog.refresh()
    client = _FakeClient(
        [
            _tool_call_message(
                "read_timeseries",
                {"source": "data_lake/vnindex_cache.csv", "latest_n": 3},
            ),
            SimpleNamespace(
                content="VNINDEX giảm trong ba phiên gần nhất [Nguồn: data_lake/vnindex_cache.csv].",
                tool_calls=None,
            ),
        ]
    )

    result = ask_ai_cio_data_agent(
        "test-key",
        "deepseek-v4-pro",
        "VNINDEX ba phiên gần nhất?",
        catalog=catalog,
        client=client,
    )

    assert result.mode == "tool_agent"
    assert result.methodology_version == DATA_AGENT_VERSION
    assert result.sources[0].relative_path == "data_lake/vnindex_cache.csv"
    assert [display["type"] for display in result.displays] == ["table", "line_chart"]
    assert result.displays[0]["rows"][0]["time"].startswith("2026-07-22")
    assert result.tool_traces[0]["tool"] == "read_timeseries"
    assert result.tool_traces[0]["ok"] is True
    assert "tools" in client.completions.requests[0]
    assert client.completions.requests[0]["tool_choice"] == "required"
    assert client.completions.requests[1]["tool_choice"] == "auto"
    tool_messages = [
        message
        for message in client.completions.requests[1]["messages"]
        if message.get("role") == "tool"
    ]
    assert "2026-07-22" in tool_messages[0]["content"]


def test_data_agent_uses_compatibility_tools_when_provider_rejects_native_tools(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/vnindex_cache.csv").write_text(
        "time,VNINDEX\n2026-07-22,1668.53\n",
        encoding="utf-8",
    )
    catalog.refresh()
    client = _FakeClient(
        [
            TypeError("tools are not supported"),
            SimpleNamespace(content="Compatibility answer with source.", tool_calls=None),
        ]
    )

    result = ask_ai_cio_data_agent(
        "test-key",
        "deepseek-v4-pro",
        "VNINDEX hiện tại?",
        catalog=catalog,
        client=client,
    )

    assert result.mode == "compatibility_agent"
    assert result.answer == "Compatibility answer with source."
    assert result.sources[0].relative_path == "data_lake/vnindex_cache.csv"
    assert [display["type"] for display in result.displays] == ["table"]
    assert result.tool_traces[0]["tool"] == "compatibility_router"
    assert "native tool calling unavailable" in result.tool_traces[0]["reason"]
    assert result.tool_traces[1]["tool"] == "read_timeseries"
    assert "tools" not in client.completions.requests[1]


def test_data_agent_uses_compatibility_tools_when_model_ignores_required_tool_call(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/vnindex_cache.csv").write_text(
        "time,VNINDEX\n2026-07-20,1743.51\n2026-07-22,1668.53\n2026-07-21,1730.56\n",
        encoding="utf-8",
    )
    catalog.refresh()
    client = _FakeClient(
        [
            SimpleNamespace(content="Answer without tools", tool_calls=None),
            SimpleNamespace(content="Answer grounded by compatibility tools.", tool_calls=None),
        ]
    )

    result = ask_ai_cio_data_agent(
        "test-key",
        "deepseek-v4-pro",
        "VNINDEX trong 3 phiên gần nhất?",
        catalog=catalog,
        client=client,
    )

    assert result.mode == "compatibility_agent"
    assert [row["time"] for row in result.displays[0]["rows"]] == [
        "2026-07-22",
        "2026-07-21",
        "2026-07-20",
    ]
    assert [display["type"] for display in result.displays] == ["table", "line_chart"]
    assert result.tool_traces[0]["reason"] == "model returned no tool call"


def test_local_provider_defaults_directly_to_compatibility_tools(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/vnindex_cache.csv").write_text(
        "time,VNINDEX\n2026-07-22,1668.53\n",
        encoding="utf-8",
    )
    catalog.refresh()
    client = _FakeClient([SimpleNamespace(content="Local compatibility answer.", tool_calls=None)])

    result = ask_ai_cio_data_agent(
        "test-key",
        "chatgpt-local",
        "VNINDEX hiện tại?",
        catalog=catalog,
        client=client,
    )

    assert result.mode == "compatibility_agent"
    assert result.tool_traces[0]["reason"] == "localhost provider defaults to compatibility mode"
    assert len(client.completions.requests) == 1
    assert "tools" not in client.completions.requests[0]


def test_systemic_risk_question_uses_metrics_anchor_and_five_session_confirmation(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    _write_systemic_risk_snapshot(tmp_path)
    (tmp_path / "data_lake/vnindex_cache.csv").write_text(
        "time,VNINDEX,VNINDEX_volume\n"
        "2026-07-17,1780.00,700000000\n"
        "2026-07-20,1743.51,862568937\n"
        "2026-07-21,1730.56,789069211\n"
        "2026-07-22,1668.53,915046404\n",
        encoding="utf-8",
    )
    catalog.refresh()
    client = _FakeClient(
        [
            SimpleNamespace(
                content=(
                    "Rủi ro hệ thống ở mức PRE-CRASH / PANIC, do breadth và điều kiện tài chính "
                    "chi phối [Nguồn: data_lake/ai_cio_metrics/latest_chatgpt-local.json]."
                ),
                tool_calls=None,
            )
        ]
    )

    result = ask_ai_cio_data_agent(
        "test-key",
        "chatgpt-local",
        "Rủi ro hệ thống hiện tại là gì và tín hiệu nào đang chi phối?",
        catalog=catalog,
        client=client,
    )

    assert result.mode == "compatibility_agent"
    assert [trace["tool"] for trace in result.tool_traces] == [
        "compatibility_router",
        "get_tool_metrics",
        "read_timeseries",
    ]
    assert result.tool_traces[2]["arguments"]["latest_n"] == 5
    assert [display["type"] for display in result.displays] == ["table", "table", "line_chart"]
    assert {source.relative_path for source in result.sources} == {
        "data_lake/ai_cio_metrics/latest_chatgpt-local.json",
        "data_lake/vnindex_cache.csv",
    }
    prompt = client.completions.requests[0]["messages"][-1]["content"]
    assert "PRE-CRASH / PANIC" in prompt
    assert "Breadth MA20 <25% (6.1%)" in prompt
    assert "2026-07-22" in prompt


def test_toolbox_blocks_timeseries_path_traversal(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    outside = tmp_path.parent / "agent-outside.csv"
    outside.write_text("date,value\n2026-07-22,1\n", encoding="utf-8")
    try:
        execution = DataAgentToolbox(catalog, "chatgpt-local").execute(
            "read_timeseries",
            {"source": f"../{outside.name}", "latest_n": 3},
        )
    finally:
        outside.unlink(missing_ok=True)

    assert execution.payload["ok"] is False
    assert "ngoài phạm vi" in execution.payload["error"]


def test_timeseries_parser_handles_vietnamese_day_month_dates(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/local_dates.csv").write_text(
        "date,value\n01/07/2026,1\n22/07/2026,3\n15/07/2026,2\n",
        encoding="utf-8",
    )
    catalog.refresh()

    execution = DataAgentToolbox(catalog, "chatgpt-local").execute(
        "read_timeseries",
        {"source": "data_lake/local_dates.csv", "latest_n": 2},
    )

    assert execution.payload["ok"] is True
    assert [row["date"] for row in execution.payload["rows"]] == ["2026-07-22", "2026-07-15"]


def test_cloud_provider_filter_removes_localhost_endpoints() -> None:
    providers = available_provider_keys(cloud_runtime=True)

    assert "chatgpt-local" not in providers
    assert "kimi-2.6-local" not in providers
    assert "deepseek-v4-pro" in providers
    assert is_local_provider("chatgpt-local") is True
    assert is_local_provider("deepseek-v4-pro") is False


def test_data_agent_blocks_local_provider_when_cloud_override_is_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUANT_PLATFORM_CLOUD_RUNTIME", "true")

    with pytest.raises(ValueError, match="localhost không khả dụng trên cloud"):
        ask_ai_cio_data_agent(
            "test-key",
            "chatgpt-local",
            "VNINDEX hiện tại?",
            catalog=_catalog(tmp_path),
        )


def test_bounded_tool_content_remains_valid_json() -> None:
    content = _bounded_tool_content(
        {
            "ok": True,
            "rows": [{"label": f"row-{index}", "value": "x" * 2_000} for index in range(100)],
        }
    )

    decoded = json.loads(content)
    assert len(content) <= MAX_TOOL_RESULT_CHARS
    assert decoded["ok"] is True
    assert decoded["_truncated"] is True


def test_catalog_manifest_is_deterministic_and_contains_schema_not_values(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "data_lake/sample_metrics.csv").write_text(
        "date,metric\n2026-07-22,TOP_SECRET_VALUE\n",
        encoding="utf-8",
    )
    catalog.refresh()

    manifest_path = catalog.write_manifest()
    first_content = manifest_path.read_text(encoding="utf-8")
    catalog.write_manifest()
    second_content = manifest_path.read_text(encoding="utf-8")

    assert first_content == second_content
    assert "date, metric" in first_content
    assert "TOP_SECRET_VALUE" not in first_content

    loaded = ProjectDataCatalog(
        root_dir=tmp_path,
        data_roots=("data_lake", "reports", "docs", "config"),
        root_files=(),
        use_manifest=True,
    )
    assert loaded.stats()["total_files"] == 1
    assert str(loaded.stats()["refreshed_at"]).startswith("manifest:")


def test_unknown_agent_tool_is_rejected(tmp_path: Path) -> None:
    execution = DataAgentToolbox(_catalog(tmp_path), "chatgpt-local").execute(
        "run_shell",
        {"command": "whoami"},
    )

    assert execution.payload == {"ok": False, "error": "Tool không được phép: run_shell"}
