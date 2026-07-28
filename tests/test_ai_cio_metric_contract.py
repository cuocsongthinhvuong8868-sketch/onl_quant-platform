import json

import pytest

from shared import ai_cio
from shared.ai_cio_metric_contract import (
    DIRECT_METRIC_SOURCE,
    PROSE_FALLBACK_SOURCE,
    STRUCTURED_TAIL_SOURCE,
    TOOL_METRIC_ALIASES,
    append_direct_metrics,
    resolve_tool_metrics,
)


def _tail(tool: str, **metrics) -> str:
    return "```json\n" + json.dumps({"tool": tool, **metrics}) + "\n```"


def test_market_breadth_27_july_format_uses_actual_not_reference_threshold():
    report = """
    ## Observations
    - **MA20 (1M): 7.8%** - oversold.

    ## Structural Health
    Bear Confirmed: MA20 < 30% (thực tế 7.8%).

    ## Structured Tail
    ```json
    {
      "tool": "market_breadth",
      "ma20_pct": 7.8,
      "ma60_pct": 10.4,
      "regime": "bear_confirmed"
    }
    ```
    """

    packet = ai_cio._build_evidence_packet(
        "market_breadth",
        report,
        "current_tool",
        "27/07/2026",
    )

    assert packet["key_metrics"]["breadth_ma20_pct"] == 7.8
    assert packet["metric_provenance"]["breadth_ma20_pct"] == STRUCTURED_TAIL_SOURCE
    assert packet["adapter_score"]["tool_score"] == 18


def test_direct_quantitative_metric_blocks_conflicting_tail_and_prose():
    report = "MA20: 30.0%\n" + _tail("market_breadth", ma20_pct=30.0)
    report = append_direct_metrics(
        report,
        "market_breadth",
        {"breadth_ma20_pct": 7.8},
    )

    resolution = resolve_tool_metrics("market_breadth", report)

    assert resolution.metrics["breadth_ma20_pct"] == 7.8
    assert resolution.provenance["breadth_ma20_pct"] == DIRECT_METRIC_SOURCE
    assert resolution.consistency["status"] == "WARN_BLOCKED_LOWER_PRIORITY"
    blocked_sources = {
        item["blocked_source"]
        for item in resolution.consistency["blocked_candidates"]
        if item["metric"] == "breadth_ma20_pct"
    }
    assert blocked_sources == {STRUCTURED_TAIL_SOURCE, PROSE_FALLBACK_SOURCE}


def test_in_memory_direct_metric_has_highest_priority():
    report = _tail("esr_monitor", ssi_pct=80.0) + "\nSSI: 90.0%"

    resolution = resolve_tool_metrics(
        "esr_monitor",
        report,
        direct_metrics={"ssi_pct": 63.4},
    )

    assert resolution.metrics["ssi_pct"] == 63.4
    assert resolution.provenance["ssi_pct"] == DIRECT_METRIC_SOURCE
    assert len(resolution.consistency["blocked_candidates"]) == 2


@pytest.mark.parametrize(
    ("tool_id", "tail_key", "canonical_key"),
    [
        (tool_id, aliases[-1], canonical_key)
        for tool_id, schema in TOOL_METRIC_ALIASES.items()
        for canonical_key, aliases in [next(iter(schema.items()))]
    ],
)
def test_every_registered_tool_schema_reads_structured_tail(
    tool_id,
    tail_key,
    canonical_key,
):
    resolution = resolve_tool_metrics(
        tool_id,
        _tail(tool_id, **{tail_key: 12.5}),
    )

    assert resolution.metrics[canonical_key] == 12.5
    assert resolution.provenance[canonical_key] == STRUCTURED_TAIL_SOURCE
    assert resolution.consistency["status"] == "PASS_STRUCTURED"


def test_prose_regexes_are_tool_specific_and_cannot_cross_contaminate():
    report = "FearGreed Risk Score: 42.0\nBreadth MA20: 99.0%\nEVT Xi: 0.9"

    resolution = resolve_tool_metrics("fear_greed", report)

    assert resolution.metrics == {"fear_greed_score": 42.0}
    assert "breadth_ma20_pct" not in resolution.metrics
    assert "evt_xi" not in resolution.metrics


def test_regex_remains_available_as_legacy_fallback():
    resolution = resolve_tool_metrics(
        "credit_spread",
        "Credit Spread Risk Premium: 340.8 bps",
    )

    assert resolution.metrics["credit_spread_risk_premium_bps"] == 340.8
    assert resolution.provenance["credit_spread_risk_premium_bps"] == PROSE_FALLBACK_SOURCE
    assert resolution.consistency["status"] == "FALLBACK_ONLY"


def test_metrics_snapshot_exposes_authority_and_consistency_audit():
    report = append_direct_metrics(
        _tail("market_breadth", ma20_pct=30.0),
        "market_breadth",
        {"breadth_ma20_pct": 7.8},
    )
    packet = ai_cio._build_evidence_packet("market_breadth", report, "current_tool")

    snapshot = ai_cio._build_tool_metrics_snapshot([packet])["market_breadth"]

    assert snapshot["key_metrics"]["breadth_ma20_pct"] == 7.8
    assert snapshot["metric_authority"] == DIRECT_METRIC_SOURCE
    assert snapshot["data_quality"] == DIRECT_METRIC_SOURCE
    assert snapshot["metric_consistency"]["status"] == "WARN_BLOCKED_LOWER_PRIORITY"
