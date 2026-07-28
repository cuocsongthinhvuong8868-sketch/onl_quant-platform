import json
from pathlib import Path
from datetime import date

from config import ROOT_DIR
from shared.pdf_export import (
    _build_model,
    _extract_confidence,
    _extract_executive_order,
    _extract_tail_risk,
    _load_metrics_snapshot,
    create_ai_cio_pdf,
    load_ai_cio_history,
)


def test_pdf_order_parser_prefers_last_authoritative_normalized_block():
    report = """
- **Cash**: **80%**
- **Equity**: **20%**
- **Short VN30F1M**: **10%**

**Deterministic Normalized Executive Order**
- **Cash**: **100%**
- **Equity**: **0%**
- **Short VN30F1M**: **0%**
"""

    orders = {item["sleeve"]: item["target"] for item in _extract_executive_order(report)}

    assert orders == {
        "Cash": "100%",
        "Equity": "0%",
        "Short VN30F1M": "0%",
    }


def test_pdf_order_parser_ignores_structured_sleeves_after_final_line():
    report = """
### 6. Executive Order
- **Cash**: **85%**
- **Equity**: **15%**
- **Short VN30F1M**: **0%**

final score & regime : 24 ; regime : PRE-CRASH / PANIC

- **Cash**: **20%**
- **Equity**: **80%**
- **Short VN30F1M**: **10%**
"""

    orders = {item["sleeve"]: item["target"] for item in _extract_executive_order(report)}

    assert orders["Cash"] == "85%"
    assert orders["Equity"] == "15%"
    assert orders["Short VN30F1M"] == "0%"


def test_pdf_metrics_loader_does_not_cross_provider_boundaries(tmp_path):
    metrics_dir = tmp_path / "ai_cio_metrics"
    metrics_dir.mkdir()
    (metrics_dir / "metrics_120726.json").write_text(
        '{"provider":"deepseek-v4-pro","report_date":"12/07/2026"}',
        encoding="utf-8",
    )
    (metrics_dir / "metrics_chatgpt-local_120726.json").write_text(
        '{"provider":"chatgpt-local","report_date":"12/07/2026","marker":"right"}',
        encoding="utf-8",
    )

    payload = _load_metrics_snapshot(tmp_path, date(2026, 7, 12), "chatgpt-local")
    missing = _load_metrics_snapshot(tmp_path, date(2026, 7, 12), "kimi-2.6")

    assert payload["marker"] == "right"
    assert missing == {}


def test_load_ai_cio_history_ignores_malformed_rows_and_appends_report_date(tmp_path):
    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider\n"
        "10072026,27,PRE-CRASH / PANIC,auto,deepseek-v4-pro\n"
        "<<<<<<< HEAD,,,,\n"
        "11072026,31,FEAR / DISTRIBUTION,auto,deepseek-v4-pro\n"
        "bad-date,not-a-score,BROKEN,,\n",
        encoding="utf-8",
    )

    history = load_ai_cio_history(
        data_lake=data_lake,
        provider_key="chatgpt-local",
        target_date=date(2026, 7, 12),
        final_score=28,
        final_regime="PRE-CRASH / PANIC",
        final_stress_regime="PRE-CRASH / PANIC",
        final_capitulation_phase="FRAGILE",
        final_capitulation_action_eligible=False,
    )

    assert [point.date.isoformat() for point in history] == [
        "2026-07-10",
        "2026-07-11",
        "2026-07-12",
    ]
    assert history[-1].source == "report"
    assert history[-1].stress_regime == "PRE-CRASH / PANIC"
    assert history[-1].capitulation_phase == "FRAGILE"
    assert history[-1].capitulation_action_eligible is False


def test_load_ai_cio_history_preserves_persisted_capitulation_fields(tmp_path):
    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider,stress_regime,capitulation_phase,sessions_after_three_gate_climax,capitulation_action_eligible\n"
        "12072026,12,CAPITULATION,auto,deepseek-v4-pro,EXTREME CRISIS,CAPITULATION_CLIMAX_CONTINUATION,2,true\n",
        encoding="utf-8",
    )

    history = load_ai_cio_history(
        data_lake=data_lake,
        provider_key="deepseek-v4-pro",
    )

    assert len(history) == 1
    assert history[0].stress_regime == "EXTREME CRISIS"
    assert history[0].capitulation_phase == "CAPITULATION_CLIMAX_CONTINUATION"
    assert history[0].sessions_after_three_gate_climax == 2
    assert history[0].capitulation_action_eligible is True


def test_load_ai_cio_history_enriches_legacy_selected_report_row(tmp_path):
    data_lake = tmp_path / "data_lake"
    data_lake.mkdir()
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider\n"
        "12072026,12,CAPITULATION,auto,deepseek-v4-pro\n",
        encoding="utf-8",
    )

    history = load_ai_cio_history(
        data_lake=data_lake,
        provider_key="deepseek-v4-pro",
        target_date=date(2026, 7, 12),
        final_score=12,
        final_regime="CAPITULATION",
        final_stress_regime="EXTREME CRISIS",
        final_capitulation_phase="CAPITULATION_CLIMAX_CONTINUATION",
        final_sessions_after_three_gate_climax=1,
        final_capitulation_action_eligible=True,
    )

    assert history[0].stress_regime == "EXTREME CRISIS"
    assert history[0].capitulation_phase == "CAPITULATION_CLIMAX_CONTINUATION"
    assert history[0].sessions_after_three_gate_climax == 1
    assert history[0].capitulation_action_eligible is True


def test_create_ai_cio_pdf_smoke(tmp_path):
    data_lake = tmp_path / "data_lake"
    (data_lake / "ai_cio_metrics").mkdir(parents=True)
    (data_lake / "daily_cache").mkdir()
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider\n"
        "10072026,27,PRE-CRASH / PANIC,auto,deepseek-v4-pro\n"
        "11072026,31,FEAR / DISTRIBUTION,auto,deepseek-v4-pro\n",
        encoding="utf-8",
    )
    (data_lake / "ai_cio_metrics" / "metrics_120726.json").write_text(
        """
        {
          "provider": "chatgpt-local",
          "report_date": "12/07/2026",
          "data_date": "10/07/2026",
          "score_anchor": {
            "metric_implied_subscores": {
              "macro_risk_score": 25,
              "market_internal_score": 13,
              "tail_risk_score": 35
            },
            "score_band_reason": {"macro": ["VNIBOR ON >=4%"], "tail": ["SSI >=55%"]},
            "hard_constraints": ["Breadth MA20 weak"]
          },
          "tools": {
            "market_breadth": {
              "tool_score": 18,
              "tool_regime": "PRE-CRASH / PANIC",
              "tool_bias": "bearish",
              "score_reason": "Breadth MA20 <25%"
            }
          },
          "history": {
            "rolling_summary": {
              "score_change_1d": 1,
              "score_change_5d": -3,
              "current_regime_streak": 2
            }
          }
        }
        """,
        encoding="utf-8",
    )

    report = """
### EXECUTIVE BOTTOM LINE
- **Điểm số tổng hợp (Composite Score)**: **28/100**
- **Trạng thái vĩ mô (Regime)**: **PRE-CRASH / PANIC**
- **Mức rủi ro đuôi (Tail Risk)**: **Elevated**

Bức tranh tổng thể vẫn là phòng thủ và cần giữ risk budget thấp.

### 6. Executive Order
- **Cash**: **95%**
- **Equity**: **5%**, chỉ tactical, không margin.
- **Short VN30F1M**: **0%**.

final score & regime : 28 ; regime : PRE-CRASH / PANIC
"""
    output = tmp_path / "report.pdf"
    create_ai_cio_pdf(
        report,
        output,
        report_date="120726",
        provider_key="chatgpt-local",
        data_lake=data_lake,
        root_dir=ROOT_DIR,
    )

    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 10_000


def test_tail_risk_parser_skips_score_line_and_reads_label():
    report = """
**Điểm số tổng hợp**: **27/100**
*[Macro Risk: 20/100 | Market Internal: 13/100 | Tail Risk: 35/100]*
**Mức rủi ro đuôi**: Elevated
"""

    assert _extract_tail_risk(report) == "ELEVATED"


def test_build_model_uses_legacy_context_metric_values_for_tail_cards(tmp_path):
    data_lake = tmp_path / "data_lake"
    (data_lake / "daily_cache").mkdir(parents=True)
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider\n",
        encoding="utf-8",
    )
    (data_lake / "daily_cache" / "ai_cio_context_deepseek-v4-pro_130726.json").write_text(
        """
        {
          "decision_state": {
            "data_date": "13/07/2026",
            "metric_values": {
              "esr_monitor.ssi_pct": 63.0,
              "var_cvar_vnindex.evt_xi": 0.345,
              "abm_simulator.abm_early_warning_score": 45.0
            },
            "tool_scores": [
              {
                "tool": "esr_monitor",
                "tool_score": 42,
                "tool_regime": "FEAR / DISTRIBUTION",
                "tool_bias": "neutral_or_mixed",
                "score_reason": "SSI >=55% (63.0%)"
              }
            ],
            "metric_implied_subscores": {
              "macro_risk_score": 20,
              "market_internal_score": 13,
              "tail_risk_score": 35
            }
          }
        }
        """,
        encoding="utf-8",
    )

    report = """
**Điểm số tổng hợp**: **27/100**
*[Macro Risk: 20/100 | Market Internal: 13/100 | Tail Risk: 35/100]*
**Mức rủi ro đuôi**: Elevated
final score & regime : 27 ; regime : PRE-CRASH / PANIC
"""

    model = _build_model(report, date(2026, 7, 13), "deepseek-v4-pro", data_lake)

    assert model["tail_risk"] == "ELEVATED"
    assert model["subscores"]["tail_risk_score"] == 35
    assert model["metrics_tools"]["esr_monitor"]["key_metrics"]["ssi_pct"] == 63.0
    assert model["metrics_tools"]["var_cvar_vnindex"]["key_metrics"]["evt_xi"] == 0.345
    assert model["metrics_tools"]["abm_simulator"]["key_metrics"]["abm_early_warning_score"] == 45.0


def test_build_model_uses_bold_confidence_and_final_metrics_state(tmp_path):
    data_lake = tmp_path / "data_lake"
    (data_lake / "daily_cache").mkdir(parents=True)
    metrics_dir = data_lake / "ai_cio_metrics"
    metrics_dir.mkdir()
    (data_lake / "Ai_cio_report.csv").write_text(
        "ddmmyyyy,score,regime,source,provider\n",
        encoding="utf-8",
    )
    (data_lake / "daily_cache" / "ai_cio_context_deepseek-v4-pro_130726.json").write_text(
        json.dumps(
            {
                "decision_state": {
                    "metric_implied_score": 24,
                    "stress_regime": "PRE-CRASH / PANIC",
                    "resolved_regime": "PRE-CRASH / PANIC",
                }
            }
        ),
        encoding="utf-8",
    )
    (metrics_dir / "metrics_deepseek-v4-pro_130726.json").write_text(
        json.dumps(
            {
                "provider": "deepseek-v4-pro",
                "report_date": "13/07/2026",
                "final_output": {
                    "score": 31,
                    "stress_regime": "FEAR / DISTRIBUTION",
                    "resolved_regime": "FEAR / DISTRIBUTION",
                    "confidence": "low",
                },
            }
        ),
        encoding="utf-8",
    )
    report = (
        "- **Final confidence**: **LOW**\n\n"
        "final score & regime : 31 ; regime : FEAR / DISTRIBUTION"
    )

    model = _build_model(report, date(2026, 7, 13), "deepseek-v4-pro", data_lake)

    assert model["confidence"] == "LOW"
    assert model["history"][-1].stress_regime == "FEAR / DISTRIBUTION"
    assert model["history"][-1].regime == "FEAR / DISTRIBUTION"
    assert _extract_confidence("- **Final confidence**: **LOW**") == "LOW"

    metrics_fallback = _build_model(
        "final score & regime : 31 ; regime : FEAR / DISTRIBUTION",
        date(2026, 7, 13),
        "deepseek-v4-pro",
        data_lake,
    )
    assert metrics_fallback["confidence"] == "LOW"
