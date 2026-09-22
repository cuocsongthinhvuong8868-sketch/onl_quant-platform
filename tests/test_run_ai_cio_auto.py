from __future__ import annotations

import csv
from pathlib import Path

import pytest

from command import run_ai_cio_auto as auto
from shared import ai_cio
from shared.pdf_export import create_ai_cio_pdf, load_ai_cio_history
from tools.humility_falsification import page as humility_page


def test_daily_report_uses_python_rules_without_an_api_key(monkeypatch) -> None:
    calls = []

    def generate(api_key, **kwargs):
        calls.append((api_key, kwargs))
        return "quantitative report"

    monkeypatch.setattr(auto, "run_executive_summary", generate)

    assert auto._get_report_text() == "quantitative report"
    assert calls == [
        (
            "",
            {
                "provider_key": ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
                "force": False,
                "source": "auto",
                "report_mode": "deterministic",
            },
        )
    ]


def test_deterministic_pipeline_does_not_construct_a_remote_model(monkeypatch) -> None:
    def remote_model(*args, **kwargs):
        raise AssertionError("Remote model must not be constructed")

    def stop_after_client_setup():
        raise RuntimeError("local pipeline reached")

    monkeypatch.setattr(ai_cio, "OpenAI", remote_model)
    monkeypatch.setattr(ai_cio, "load_close_prices", stop_after_client_setup)

    with pytest.raises(RuntimeError, match="local pipeline reached"):
        ai_cio.run_executive_summary(
            "",
            provider_key=ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
            report_mode="deterministic",
        )

    with pytest.raises(ValueError, match="cannot call a language model"):
        ai_cio.run_executive_summary(
            "some-key",
            provider_key=ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
        )


def test_daily_runner_keeps_pdf_history_and_telegram_without_a_model(
    monkeypatch, tmp_path: Path
) -> None:
    report = "# Quant report\n\nfinal score & regime : 25 ; regime : PRE-CRASH / PANIC"
    pdf_path = tmp_path / "reports" / "daily.pdf"
    calls = []

    monkeypatch.setattr(auto, "PDF_PATH", pdf_path)
    monkeypatch.setattr(auto, "REPORTS_DIR", pdf_path.parent)
    monkeypatch.setattr(auto, "_get_report_text", lambda: report)

    def create_pdf(text, path, **kwargs):
        calls.append(("pdf", text, kwargs["provider_key"]))
        path.write_bytes(b"%PDF-test")

    def summarize(api_key, text, **kwargs):
        calls.append(("summary", api_key, kwargs["provider_key"], kwargs["force"]))
        return "daily brief"

    monkeypatch.setattr(auto, "create_ai_cio_pdf", create_pdf)
    monkeypatch.setattr(auto, "summarize_executive_report_for_telegram", summarize)
    monkeypatch.setattr(
        auto,
        "_send_telegram",
        lambda score, regime, brief: calls.append(("telegram", score, regime, brief)),
    )

    auto.main()

    assert pdf_path.read_bytes() == b"%PDF-test"
    assert calls == [
        ("pdf", report, ai_cio.AI_CIO_DETERMINISTIC_PROVIDER),
        ("summary", "", ai_cio.AI_CIO_DETERMINISTIC_PROVIDER, True),
        ("telegram", "25", "PRE-CRASH / PANIC", "daily brief"),
    ]


def test_rules_report_uses_snapshot_score_and_guardrails(tmp_path: Path) -> None:
    state = {
        "metric_implied_score": 25,
        "metric_implied_subscores": {
            "macro_risk_score": 20,
            "market_internal_score": 30,
            "tail_risk_score": 25,
        },
        "hard_constraints": ["Breadth MA20 weak at 31.0%"],
        "capitulation_state": {"phase": "FRAGILE", "action_eligible": False},
    }
    snapshot = {
        "history": {"rolling_summary": {"score_change_1d": -2}},
        "tools": {
            "market_breadth": {
                "as_of": "22/09/2026",
                "scoring_eligible": True,
                "tool_score": 31,
                "tool_regime": "FEAR / DISTRIBUTION",
                "data_quality": "direct_quantitative",
            },
        },
    }

    body = ai_cio._render_rule_based_executive_report(
        state, snapshot, "22/09/2026", "22/09/2026"
    )
    report = ai_cio._render_deterministic_report_fields(body, state, "22/09/2026")

    assert "| market_breadth | 22/09/2026 | 31 |" in report
    assert "Breadth MA20 weak at 31.0%" in report
    assert "- **Equity**: **0%**" in report
    assert ai_cio.parse_score_regime(report) == ("25", "PRE-CRASH / PANIC")
    pdf_path = create_ai_cio_pdf(
        report,
        tmp_path / "daily.pdf",
        report_date="220926",
        provider_key=ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
        data_lake=tmp_path,
    )
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_rules_report_fails_when_score_is_missing() -> None:
    with pytest.raises(ValueError, match="score is unavailable"):
        ai_cio._render_rule_based_executive_report({}, {}, "22/09/2026", "22/09/2026")


def test_rules_provider_persists_daily_score_history(monkeypatch, tmp_path: Path) -> None:
    history_path = tmp_path / "Ai_cio_report.csv"
    monkeypatch.setattr(ai_cio, "CSV_HISTORY_PATH", history_path)

    assert ai_cio.upsert_history_csv(
        "25",
        "PRE-CRASH / PANIC",
        source="auto",
        provider=ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
    )
    with history_path.open(encoding="utf-8", newline="") as history_file:
        rows = list(csv.DictReader(history_file))
    assert len(rows) == 1
    assert rows[0]["provider"] == "quant-rules-v1"
    assert rows[0]["source"] == "auto"


def test_rules_pdf_history_includes_previous_daily_scores(tmp_path: Path) -> None:
    history_path = tmp_path / "Ai_cio_report.csv"
    with history_path.open("w", encoding="utf-8", newline="") as history_file:
        writer = csv.DictWriter(history_file, fieldnames=ai_cio.CSV_HISTORY_HEADER)
        writer.writeheader()
        for day, provider in (
            ("14092026", "deepseek-v4-pro"),
            ("15092026", "deepseek-v4-pro"),
            ("16092026", "quant-rules-v1"),
            ("17092026", "quant-rules-v1"),
            ("18092026", "quant-rules-v1"),
        ):
            writer.writerow({
                "ddmmyyyy": day,
                "score": "25",
                "regime": "PRE-CRASH / PANIC",
                "source": "auto",
                "provider": provider,
            })

    history = load_ai_cio_history(
        data_lake=tmp_path,
        provider_key=ai_cio.AI_CIO_DETERMINISTIC_PROVIDER,
    )
    assert len(history) == 5
    assert history[0].provider == "deepseek-v4-pro"


def test_humility_monitor_discovers_rules_reports(monkeypatch, tmp_path: Path) -> None:
    daily_cache = tmp_path / "daily_cache"
    daily_cache.mkdir()
    report_path = daily_cache / "executive_summary_quant-rules-v1_180926.txt"
    report_path.write_text("quantitative report", encoding="utf-8")
    monkeypatch.setattr(humility_page, "DATA_LAKE", tmp_path)

    assert humility_page._reports_by_provider()["quant-rules-v1"] == [report_path]


def test_scheduled_workflows_do_not_supply_ai_provider_secrets() -> None:
    root = Path(__file__).resolve().parent.parent
    for name in ("ai_cio_daily.yml", "command_runner.yml"):
        workflow = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY" not in workflow
        assert "MOONSHOT_API_KEY" not in workflow
