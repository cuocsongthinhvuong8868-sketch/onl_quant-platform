import json
from pathlib import Path

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
