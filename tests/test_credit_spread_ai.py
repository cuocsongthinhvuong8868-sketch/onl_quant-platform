from datetime import date

import pandas as pd
import pytest

from tools.credit_spread.ai_analysis import (
    CACHE_VERSION,
    build_credit_spread_prompt,
    build_credit_spread_snapshot,
    build_structured_context,
    decode_cache,
    encode_cache,
)
from tools.credit_spread.report import snapshot as report_snapshot


def _snapshot_issuance() -> pd.DataFrame:
    rows = []
    for index, report_date in enumerate(pd.date_range("2026-01-02", periods=10, freq="7D")):
        rows.extend(
            [
                {
                    "report_date": report_date,
                    "sector": "bank",
                    "coupon_rate_pct": 7.0 + index * 0.05,
                    "issue_value_bn_vnd": 100.0,
                    "maturity_bucket": "<=3Y",
                },
                {
                    "report_date": report_date,
                    "sector": "bank",
                    "coupon_rate_pct": 7.2 + index * 0.05,
                    "issue_value_bn_vnd": 200.0,
                    "maturity_bucket": ">5Y",
                },
                {
                    "report_date": report_date,
                    "sector": "real_estate",
                    "coupon_rate_pct": 10.0 + index * 0.15,
                    "issue_value_bn_vnd": 150.0,
                    "maturity_bucket": "<=3Y",
                },
                {
                    "report_date": report_date,
                    "sector": "real_estate",
                    "coupon_rate_pct": 10.2 + index * 0.15,
                    "issue_value_bn_vnd": 250.0,
                    "maturity_bucket": ">5Y",
                },
            ]
        )
    return pd.DataFrame(rows)


def test_canonical_snapshot_contains_trend_quality_and_recent_table():
    snapshot = build_credit_spread_snapshot(_snapshot_issuance())

    assert snapshot["matched_periods"] == 10
    assert snapshot["maturity_scope"] == "all"
    assert snapshot["weighting"] == "equal"
    assert snapshot["risk_premium_change_3p_bps"] == pytest.approx(30.0)
    assert snapshot["trend_3p"] == "WIDENING_3P"
    assert snapshot["data_quality"] == "MEDIUM"
    assert "risk_premium_bps" in snapshot["recent_table"]


def test_report_snapshot_reuses_canonical_credit_spread_snapshot(monkeypatch):
    canonical = build_credit_spread_snapshot(_snapshot_issuance())
    monkeypatch.setattr(
        "tools.credit_spread.report.load_canonical_snapshot",
        lambda: canonical,
    )

    row = report_snapshot()

    assert row["snapshot_date"] == canonical["data_date_iso"]
    assert row["risk_premium_bps"] == 390.0
    assert row["risk_premium_change_3p_bps"] == 30.0
    assert row["trend_3p"] == "WIDENING_3P"
    assert row["matched_periods"] == 10
    assert row["status"] == "ok"


def test_prompt_replaces_canonical_inputs_and_preserves_guardrails():
    prompt = build_credit_spread_prompt(build_credit_spread_snapshot(_snapshot_issuance()))

    assert "{risk_premium_bps}" not in prompt
    assert "không phải option-adjusted spread" in prompt
    assert "final score & regime" in prompt
    assert "WIDENING_3P" in prompt


def test_cache_version_rejects_unversioned_or_stale_content():
    encoded = encode_cache("# Credit report")

    assert CACHE_VERSION in encoded
    assert decode_cache(encoded) == "# Credit report"
    assert decode_cache("# legacy report") is None
    assert decode_cache(encoded.replace(CACHE_VERSION, "old_method")) is None


def test_ai_cio_packet_extracts_credit_metrics_and_scores_them():
    from shared.ai_cio import _build_evidence_packet

    snapshot = build_credit_spread_snapshot(_snapshot_issuance())
    packet = _build_evidence_packet(
        "credit_spread",
        build_structured_context(snapshot),
        "macro",
        snapshot["date"],
    )

    assert packet["key_metrics"]["credit_spread_risk_premium_bps"] == pytest.approx(390.0)
    assert packet["key_metrics"]["credit_spread_3p_change_bps"] == pytest.approx(30.0)
    assert packet["key_metrics"]["credit_spread_matched_periods"] == 10
    assert packet["adapter_score"]["tool_score"] < 50
    assert packet["adapter_score"]["tool_bias"] == "bearish"


def test_credit_spread_adapter_neutralizes_thin_sample():
    from shared.ai_cio_scoring import score_tool_packet

    score = score_tool_packet(
        "credit_spread",
        {
            "credit_spread_risk_premium_bps": 500,
            "credit_spread_percentile": 100,
            "credit_spread_matched_periods": 3,
            "credit_spread_bank_count": 1,
            "credit_spread_real_estate_count": 1,
        },
    )

    assert score["tool_score"] == 50
    assert score["tool_regime"] == "CREDIT SPREAD THIN DATA"
    assert score["tool_bias"] == "neutral_or_mixed"


def test_credit_spread_child_report_writes_shared_versioned_cache(tmp_path, monkeypatch):
    import shared.ai_cio as ai_cio
    import tools.credit_spread.ai_analysis as analysis

    snapshot = build_credit_spread_snapshot(_snapshot_issuance())

    class FakeMessage:
        content = "AI report\nfinal score & regime : 40 ; regime : ELEVATED"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            assert kwargs["messages"][1]["content"].startswith("# INPUT DATA")
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path / "data_lake")
    monkeypatch.setattr(analysis, "load_canonical_snapshot", lambda: snapshot)
    monkeypatch.setattr(ai_cio, "date", type("FixedDate", (date,), {"today": classmethod(lambda cls: date(2026, 3, 6))}))

    result = ai_cio.run_credit_spread_child_report(
        FakeClient(),
        provider_key="deepseek-v4-pro",
        model="test-model",
        force=True,
    )

    cache = tmp_path / "data_lake" / "daily_cache" / "credit_spread_deepseek-v4-pro_060326.txt"
    assert "AI report" in result
    assert cache.exists()
    assert CACHE_VERSION in cache.read_text(encoding="utf-8")
    assert "Credit Spread Risk Premium" in cache.read_text(encoding="utf-8")
