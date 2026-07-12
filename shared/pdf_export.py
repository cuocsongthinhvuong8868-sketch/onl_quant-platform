from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

from config import DATA_LAKE, ROOT_DIR


NAVY = (11, 31, 51)
INK = (38, 50, 56)
INK_700 = (77, 91, 99)
INK_500 = (122, 137, 146)
SURFACE = (243, 246, 248)
RULE = (220, 227, 232)
WHITE = (255, 255, 255)
RED = (180, 35, 24)
RED_100 = (253, 231, 229)
AMBER = (196, 122, 0)
AMBER_100 = (255, 241, 214)
GREEN = (24, 121, 78)
GREEN_100 = (229, 244, 236)
BLUE = (31, 93, 153)
BLUE_100 = (230, 240, 250)
TEAL = (11, 110, 105)

CONFIDENTIALITY = "CONFIDENTIAL - FOR INVESTMENT DISCUSSION PURPOSES ONLY"


@dataclass
class HistoryPoint:
    date: date
    score: float
    regime: str
    source: str = ""
    provider: str = ""


def _set_color(pdf: FPDF, color: tuple[int, int, int], target: str = "text") -> None:
    if target == "fill":
        pdf.set_fill_color(*color)
    elif target == "draw":
        pdf.set_draw_color(*color)
    else:
        pdf.set_text_color(*color)


def _sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", "", text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\t", " ")
    text = text.replace("**", "").replace("__", "").replace("*", "").replace("`", "")
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # DejaVu Sans covers Vietnamese well, but not color emoji. Strip pictographs
    # to avoid tofu boxes in generated PDFs.
    return "".join(ch for ch in text if unicodedata.category(ch) != "So")


def _shorten(text: str, max_chars: int) -> str:
    clean = _sanitize_text(text)
    if len(clean) <= max_chars:
        return clean
    truncated = clean[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" .,;:")
    return f"{truncated}."


def _parse_report_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    text = str(value).strip()
    for fmt in ("%d%m%y", "%d%m%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return date.today()


def _ddmmyy(report_date: date) -> str:
    return report_date.strftime("%d%m%y")


def _display_date(report_date: date) -> str:
    return report_date.strftime("%d %B %Y")


def _score_color(score: float | int | None) -> tuple[int, int, int]:
    try:
        value = float(score)
    except Exception:
        return BLUE
    if value < 35:
        return RED
    if value < 55:
        return AMBER
    if value < 70:
        return BLUE
    return GREEN


def _score_fill(score: float | int | None) -> tuple[int, int, int]:
    try:
        value = float(score)
    except Exception:
        return BLUE_100
    if value < 35:
        return RED_100
    if value < 55:
        return AMBER_100
    if value < 70:
        return BLUE_100
    return GREEN_100


def _regime_color(regime: str) -> tuple[int, int, int]:
    lower = str(regime or "").lower()
    if any(key in lower for key in ("capitulation", "crisis", "panic", "pre-crash")):
        return RED
    if any(key in lower for key in ("fear", "distribution", "warning", "breakdown", "elevated")):
        return AMBER
    if any(key in lower for key in ("uptrend", "expansion", "bull", "greed", "positive")):
        return GREEN
    return BLUE


def _status_color(status: str, score: float | None = None) -> tuple[int, int, int]:
    lower = str(status or "").lower()
    if any(key in lower for key in ("negative", "bearish", "prohibited", "critical", "panic", "crisis", "pre-crash")):
        return RED
    if any(key in lower for key in ("watch", "warning", "caution", "elevated", "tactical", "distribution", "fear")):
        return AMBER
    if any(key in lower for key in ("positive", "supportive", "implement", "bull", "improving")):
        return GREEN
    if score is not None:
        return _score_color(score)
    return BLUE


def _text_height(pdf: FPDF, width: float, text: str, line_h: float) -> float:
    if not text:
        return line_h
    return float(
        pdf.multi_cell(
            width,
            line_h,
            text,
            dry_run=True,
            output="HEIGHT",
            new_x="LEFT",
            new_y="NEXT",
        )
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_context_state(data_lake: Path, provider_key: str, report_date: date) -> dict[str, Any]:
    if not provider_key:
        return {}
    path = data_lake / "daily_cache" / f"ai_cio_context_{provider_key}_{_ddmmyy(report_date)}.json"
    payload = _load_json(path)
    return payload.get("decision_state", {}) if isinstance(payload, dict) else {}


def _load_metrics_snapshot(data_lake: Path, report_date: date) -> dict[str, Any]:
    dated = data_lake / "ai_cio_metrics" / f"metrics_{_ddmmyy(report_date)}.json"
    payload = _load_json(dated)
    if payload:
        return payload

    latest = data_lake / "ai_cio_metrics" / "latest.json"
    payload = _load_json(latest)
    if str(payload.get("report_date", "")) == report_date.strftime("%d/%m/%Y"):
        return payload
    return {}


def load_ai_cio_history(
    data_lake: Path = DATA_LAKE,
    provider_key: str = "",
    target_date: date | None = None,
    final_score: float | None = None,
    final_regime: str = "",
) -> list[HistoryPoint]:
    """Load AI CIO score history and tolerate malformed conflict-marker rows."""
    path = data_lake / "Ai_cio_report.csv"
    if not path.exists():
        rows: list[HistoryPoint] = []
    else:
        rows = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_date = str(row.get("ddmmyyyy", "")).strip()
                if not re.fullmatch(r"\d{8}", raw_date):
                    continue
                score = _safe_float(row.get("score"))
                if score is None:
                    continue
                try:
                    parsed_date = datetime.strptime(raw_date, "%d%m%Y").date()
                except ValueError:
                    continue
                rows.append(
                    HistoryPoint(
                        date=parsed_date,
                        score=score,
                        regime=str(row.get("regime", "") or ""),
                        source=str(row.get("source", "") or ""),
                        provider=str(row.get("provider", "") or ""),
                    )
                )

    matching = [item for item in rows if provider_key and item.provider == provider_key]
    if len(matching) >= 3:
        rows = matching

    deduped: dict[date, HistoryPoint] = {}
    for item in sorted(rows, key=lambda point: point.date):
        deduped[item.date] = item
    rows = list(deduped.values())

    if target_date and final_score is not None:
        existing = next((item for item in rows if item.date == target_date), None)
        if existing is None:
            rows.append(
                HistoryPoint(
                    date=target_date,
                    score=final_score,
                    regime=final_regime,
                    source="report",
                    provider=provider_key,
                )
            )
            rows.sort(key=lambda point: point.date)

    return rows


def _extract_tail_risk(report_text: str) -> str:
    patterns = [
        r"Mức rủi ro đuôi\s*\(Tail Risk\)\*\*:\s*\*\*?([^*\n]+)",
        r"Tail Risk\*\*:\s*\*\*?([^*\n]+)",
        r"Tail risk\s*[:\-]\s*([A-Za-z ]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, report_text, flags=re.IGNORECASE)
        if match:
            return _sanitize_text(match.group(1)).upper()
    return "DATA GAP"


def _extract_confidence(report_text: str) -> str:
    match = re.search(r"Final confidence\s*:\s*\*\*?([^*.\n]+)", report_text, flags=re.IGNORECASE)
    if match:
        return _sanitize_text(match.group(1)).upper()
    match = re.search(r"Confidence\)\*\*:\s*\*\*?([^*\n]+)", report_text, flags=re.IGNORECASE)
    if match:
        return _sanitize_text(match.group(1)).upper()
    return "MEDIUM"


def _extract_horizon(report_text: str) -> str:
    match = re.search(r"(\d+\s*-\s*\d+\s*(?:phiên|sessions|ngày|days))", report_text, flags=re.IGNORECASE)
    if match:
        return _sanitize_text(match.group(1)).replace("phiên", "sessions")
    return "5-20 sessions"


def _extract_summary_paragraph(report_text: str) -> str:
    for raw in report_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-") or line.startswith("*") or line.startswith("<!--"):
            continue
        clean = _sanitize_text(line)
        if len(clean) >= 80:
            return clean
    return "Decision stance is generated from the AI CIO source report and deterministic score history."


def _extract_data_gaps(report_text: str, limit: int = 5) -> list[str]:
    gaps: list[str] = []
    for raw in report_text.splitlines():
        clean = _sanitize_text(raw)
        if "DATA INSUFFICIENT" in clean.upper() or "DATA GAP" in clean.upper():
            gaps.append(_shorten(clean, 150))
        if len(gaps) >= limit:
            break
    return gaps


def _extract_executive_order(report_text: str) -> list[dict[str, str]]:
    orders: list[dict[str, str]] = []
    sleeve_patterns = [
        ("Cash", r"^[ \t]*-[ \t]*\*\*Cash\*\*:[ \t]*\*\*?([0-9.]+%)\*\*?[ \t]*\.?[ \t]*(.*)$"),
        ("Equity", r"^[ \t]*-[ \t]*\*\*Equity\*\*:[ \t]*\*\*?([0-9.]+%)\*\*?,?[ \t]*(.*)$"),
        ("Short VN30F1M", r"^[ \t]*-[ \t]*\*\*Short VN30F1M\*\*:[ \t]*\*\*?([0-9.]+%)\*\*?[ \t]*\.?[ \t]*(.*)$"),
        ("Core stocks", r"^[ \t]*-[ \t]*\*\*Core stocks list\*\*:[ \t]*(.*)$"),
        ("Avoid list", r"^[ \t]*-[ \t]*\*\*Avoid list\*\*:[ \t]*(.*)$"),
    ]
    for sleeve, pattern in sleeve_patterns:
        match = re.search(pattern, report_text, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            continue
        if len(match.groups()) == 2:
            target = _sanitize_text(match.group(1))
            instruction = _sanitize_text(match.group(2)) or "See source report"
        else:
            target = "N/A"
            instruction = _sanitize_text(match.group(1))
        status = "NEUTRAL"
        lower = instruction.lower()
        if sleeve == "Cash":
            status = "IMPLEMENT"
        elif sleeve == "Core stocks":
            status = "DEFER" if any(key in lower for key in ("không", "chưa", "watchlist")) else "IMPLEMENT"
        elif sleeve == "Avoid list":
            status = "CAUTION"
        elif "short" in sleeve.lower():
            status = "PROHIBITED" if "0%" in target or "không" in lower else "TACTICAL"
        elif "tactical" in lower or "chỉ" in lower:
            status = "TACTICAL"
        elif "không" in lower or "0%" in target or "chưa" in lower:
            status = "DEFER"
        orders.append(
            {
                "sleeve": sleeve,
                "target": target,
                "instruction": status,
                "governance": instruction,
            }
        )
    return orders


def _metric_subscores(context_state: dict[str, Any], metrics: dict[str, Any]) -> dict[str, float]:
    subs = context_state.get("metric_implied_subscores") or metrics.get("score_anchor", {}).get("metric_implied_subscores") or {}
    result = {}
    for key in ("macro_risk_score", "market_internal_score", "tail_risk_score"):
        value = _safe_float(subs.get(key))
        if value is not None:
            result[key] = value
    return result


def _rolling_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return metrics.get("history", {}).get("rolling_summary", {}) if isinstance(metrics, dict) else {}


def _score_band_reason(context_state: dict[str, Any], metrics: dict[str, Any]) -> dict[str, list[str]]:
    raw = context_state.get("score_band_reason") or metrics.get("score_anchor", {}).get("score_band_reason") or {}
    output: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, list):
                output[key] = [_sanitize_text(item) for item in value if _sanitize_text(item)]
    return output


def _hard_constraints(context_state: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    raw = context_state.get("hard_constraints") or metrics.get("score_anchor", {}).get("hard_constraints") or []
    return [_sanitize_text(item) for item in raw if _sanitize_text(item)] if isinstance(raw, list) else []


def _tool_scores(context_state: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    raw = context_state.get("tool_scores")
    if not raw and isinstance(metrics.get("tools"), dict):
        raw = [
            {"tool": name, **payload}
            for name, payload in metrics["tools"].items()
            if isinstance(payload, dict) and payload.get("tool_score") is not None
        ]
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        score = _safe_float(item.get("tool_score"))
        rows.append(
            {
                "tool": _sanitize_text(item.get("tool", "")),
                "score": score,
                "regime": _sanitize_text(item.get("tool_regime", "")),
                "bias": _sanitize_text(item.get("tool_bias", item.get("bias", ""))),
                "reason": _sanitize_text(item.get("score_reason", item.get("reason", ""))),
            }
        )
    rows.sort(key=lambda item: (999 if item["score"] is None else item["score"]))
    return rows


def _tool_payload(metrics_tools: dict[str, Any], tool: str) -> dict[str, Any]:
    payload = metrics_tools.get(tool, {}) if isinstance(metrics_tools, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _metric_value(metrics_tools: dict[str, Any], tool: str, key: str) -> Any:
    payload = _tool_payload(metrics_tools, tool)
    metrics = payload.get("key_metrics", {})
    if isinstance(metrics, dict):
        return metrics.get(key)
    return None


def _fmt_number(value: Any, suffix: str = "", digits: int = 1) -> str:
    num = _safe_float(value)
    if num is None:
        return "DATA GAP"
    if abs(num - round(num)) < 0.05:
        return f"{num:.0f}{suffix}"
    return f"{num:.{digits}f}{suffix}"


def _parse_final_score_regime(report_text: str) -> tuple[float | None, str]:
    try:
        from shared.ai_cio import parse_score_regime

        score_raw, regime = parse_score_regime(report_text)
        return _safe_float(score_raw), _sanitize_text(regime)
    except Exception:
        return None, ""


def _build_model(
    report_text: str,
    report_date: date,
    provider_key: str,
    data_lake: Path,
) -> dict[str, Any]:
    score, regime = _parse_final_score_regime(report_text)
    context_state = _load_context_state(data_lake, provider_key, report_date)
    metrics = _load_metrics_snapshot(data_lake, report_date)

    if score is None:
        score = _safe_float(context_state.get("metric_implied_score"))
    if not regime:
        regime = _sanitize_text(context_state.get("metric_implied_regime", "DATA GAP"))

    history = load_ai_cio_history(
        data_lake=data_lake,
        provider_key=provider_key,
        target_date=report_date,
        final_score=score,
        final_regime=regime,
    )

    score_for_display = score if score is not None else 0
    return {
        "report_date": report_date,
        "display_date": _display_date(report_date),
        "provider": provider_key or metrics.get("provider", ""),
        "score": score_for_display,
        "regime": regime or "DATA GAP",
        "tail_risk": _extract_tail_risk(report_text),
        "confidence": _extract_confidence(report_text),
        "horizon": _extract_horizon(report_text),
        "summary": _extract_summary_paragraph(report_text),
        "orders": _extract_executive_order(report_text),
        "history": history,
        "subscores": _metric_subscores(context_state, metrics),
        "rolling": _rolling_summary(metrics),
        "score_band_reason": _score_band_reason(context_state, metrics),
        "hard_constraints": _hard_constraints(context_state, metrics),
        "tool_scores": _tool_scores(context_state, metrics),
        "metrics_tools": metrics.get("tools", {}) if isinstance(metrics.get("tools"), dict) else {},
        "data_gaps": _extract_data_gaps(report_text),
        "metrics_provider": metrics.get("provider", ""),
        "data_date": context_state.get("data_date") or metrics.get("data_date", ""),
    }


class _AiCioPDF(FPDF):
    def __init__(self, root_dir: Path):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.root_dir = root_dir
        self.set_margins(17, 16, 17)
        self.set_auto_page_break(auto=True, margin=15)
        self.alias_nb_pages()
        self._add_fonts()
        self.set_title("AI CIO Executive Risk & Allocation Report")
        self.set_subject("Vietnam Equity AI CIO report with score history and regime timeline")
        self.set_author("Quant Platform")
        self.set_creator("Quant Platform AI CIO PDF exporter")
        self.set_keywords("AI CIO, Vietnam Equity, market risk, regime, score history")

    @property
    def usable_w(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def _add_fonts(self) -> None:
        font_dir = self.root_dir / "fonts"
        self.add_font("DejaVu", "", str(font_dir / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(font_dir / "DejaVuSans-Bold.ttf"))

    def header(self) -> None:
        if self.page_no() <= 1:
            return
        _set_color(self, NAVY)
        self.set_font("DejaVu", "B", 6.2)
        self.set_xy(self.l_margin, 9)
        self.cell(0, 4, "INSTITUTIONAL MARKET RISK MONITOR  |  VIETNAM EQUITY", new_x="LMARGIN", new_y="NEXT")
        _set_color(self, RULE, "draw")
        self.set_line_width(0.3)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)

    def footer(self) -> None:
        if self.page_no() <= 1:
            return
        self.set_y(-11)
        _set_color(self, INK_500)
        self.set_font("DejaVu", "B", 5.8)
        self.cell(0, 4, CONFIDENTIALITY, align="C")
        self.set_x(self.w - self.r_margin - 12)
        self.cell(12, 4, str(self.page_no()), align="R")


def _section_title(pdf: _AiCioPDF, number: str, title: str, subtitle: str = "") -> None:
    pdf.set_y(max(pdf.get_y(), 21))
    x = pdf.l_margin
    y = pdf.get_y()
    _set_color(pdf, TEAL)
    pdf.set_font("DejaVu", "B", 8.5)
    pdf.set_xy(x, y + 1.2)
    pdf.cell(8, 6, number)
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(x + 10, y)
    pdf.cell(0, 8, title)
    if subtitle:
        _set_color(pdf, INK_500)
        pdf.set_font("DejaVu", "", 8.2)
        pdf.set_xy(x, y + 13)
        pdf.multi_cell(pdf.usable_w, 4.2, subtitle)
        pdf.set_y(y + 22)
    else:
        pdf.set_y(y + 13)
    _set_color(pdf, INK)


def _metric_card(
    pdf: _AiCioPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    supporting: str = "",
    color: tuple[int, int, int] = BLUE,
    fill: tuple[int, int, int] = SURFACE,
) -> None:
    _set_color(pdf, fill, "fill")
    _set_color(pdf, RULE, "draw")
    pdf.rect(x, y, w, h, style="DF")
    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "B", 6.2)
    pdf.set_xy(x + 3, y + 3)
    pdf.cell(w - 6, 3.5, label.upper())
    _set_color(pdf, color)
    pdf.set_font("DejaVu", "B", 13.5)
    pdf.set_xy(x + 3, y + 8.2)
    pdf.multi_cell(w - 6, 5.4, value)
    if supporting:
        _set_color(pdf, INK_700)
        pdf.set_font("DejaVu", "", 6.8)
        pdf.set_xy(x + 3, y + h - 8)
        pdf.multi_cell(w - 6, 3.5, supporting)


def _callout(
    pdf: _AiCioPDF,
    x: float,
    y: float,
    w: float,
    label: str,
    text: str,
    color: tuple[int, int, int] = BLUE,
    fill: tuple[int, int, int] = BLUE_100,
) -> float:
    clean = _sanitize_text(text)
    pdf.set_font("DejaVu", "", 7.8)
    body_h = _text_height(pdf, w - 10, clean, 4.1)
    h = max(18, body_h + 11)
    if y + h > 282:
        pdf.add_page()
        y = 23
    _set_color(pdf, fill, "fill")
    _set_color(pdf, fill, "draw")
    pdf.rect(x, y, w, h, style="DF")
    _set_color(pdf, color, "fill")
    pdf.rect(x, y, 1.2, h, style="F")
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 6.8)
    pdf.set_xy(x + 4, y + 3.2)
    pdf.cell(w - 8, 3.5, label.upper())
    _set_color(pdf, INK)
    pdf.set_font("DejaVu", "", 7.8)
    pdf.set_xy(x + 4, y + 8)
    pdf.multi_cell(w - 8, 4.1, clean)
    return y + h


def _gauge(pdf: _AiCioPDF, x: float, y: float, diameter: float, score: float) -> None:
    color = _score_color(score)
    _set_color(pdf, (229, 235, 239), "draw")
    pdf.set_line_width(6)
    pdf.circle(x + diameter / 2, y + diameter / 2, diameter / 2, style="D")
    _set_color(pdf, color, "draw")
    pdf.set_line_width(6)
    sweep = max(1, min(360, 360 * max(0, min(100, score)) / 100))
    pdf.arc(x, y, diameter, start_angle=-90, end_angle=-90 + sweep, clockwise=False, style="D")
    pdf.set_line_width(0.2)
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 20)
    pdf.set_xy(x, y + diameter / 2 - 7)
    pdf.cell(diameter, 8, f"{score:.0f}", align="C")
    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "", 7)
    pdf.set_xy(x, y + diameter / 2 + 2)
    pdf.cell(diameter, 4, "/ 100", align="C")
    _set_color(pdf, color)
    pdf.set_font("DejaVu", "B", 5.2)
    pdf.set_xy(x, y + diameter / 2 + 10)
    pdf.cell(diameter, 3, "COMPOSITE SCORE", align="C")


def _pillar_bar(pdf: _AiCioPDF, x: float, y: float, w: float, label: str, score: float) -> None:
    label_w = 34
    bar_w = w - label_w - 16
    color = _score_color(score)
    _set_color(pdf, INK)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_xy(x, y - 1)
    pdf.cell(label_w, 5, label, align="R")
    _set_color(pdf, (229, 235, 239), "fill")
    pdf.rect(x + label_w + 3, y, bar_w, 6, style="F")
    _set_color(pdf, color, "fill")
    pdf.rect(x + label_w + 3, y, bar_w * max(0, min(100, score)) / 100, 6, style="F")
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 7.4)
    pdf.set_xy(x + label_w + 5 + min(bar_w - 18, bar_w * score / 100), y + 0.7)
    pdf.cell(18, 4, f"{score:.0f}/100")


def _draw_table(
    pdf: _AiCioPDF,
    x: float,
    y: float,
    w: float,
    columns: list[tuple[str, float]],
    rows: list[list[str]],
    status_col: int | None = None,
    max_rows: int | None = None,
) -> float:
    rows = rows[:max_rows] if max_rows else rows
    col_widths = [w * frac for _, frac in columns]

    def header(at_y: float) -> float:
        _set_color(pdf, NAVY, "fill")
        _set_color(pdf, NAVY, "draw")
        pdf.rect(x, at_y, w, 7.2, style="DF")
        cursor_x = x
        _set_color(pdf, WHITE)
        pdf.set_font("DejaVu", "B", 6.3)
        for (title, _), cw in zip(columns, col_widths):
            pdf.set_xy(cursor_x + 1.6, at_y + 2)
            pdf.cell(cw - 3, 3, title.upper())
            cursor_x += cw
        return at_y + 7.2

    y = header(y)
    pdf.set_font("DejaVu", "", 6.9)
    for idx, row in enumerate(rows):
        clean_row = [_sanitize_text(cell) for cell in row]
        heights = []
        for cell, cw in zip(clean_row, col_widths):
            heights.append(_text_height(pdf, cw - 3.4, cell, 3.35))
        row_h = min(22, max(7.5, max(heights) + 3.2))
        if y + row_h > 282:
            pdf.add_page()
            y = header(23)
        fill = WHITE if idx % 2 == 0 else SURFACE
        _set_color(pdf, fill, "fill")
        _set_color(pdf, (235, 240, 244), "draw")
        pdf.rect(x, y, w, row_h, style="DF")
        cursor_x = x
        for col_idx, (cell, cw) in enumerate(zip(clean_row, col_widths)):
            if status_col is not None and col_idx == status_col:
                _set_color(pdf, _status_color(cell))
                pdf.set_font("DejaVu", "B", 6.9)
            else:
                _set_color(pdf, INK)
                pdf.set_font("DejaVu", "", 6.9)
            pdf.set_xy(cursor_x + 1.7, y + 1.8)
            pdf.multi_cell(cw - 3.4, 3.35, cell, new_x="RIGHT", new_y="TOP")
            cursor_x += cw
        y += row_h
    _set_color(pdf, INK)
    return y


def _draw_history_chart(pdf: _AiCioPDF, history: list[HistoryPoint], x: float, y: float, w: float, h: float) -> None:
    if len(history) < 2:
        _callout(pdf, x, y, w, "History unavailable", "Not enough valid AI CIO history rows to render a time-series chart.")
        return

    points = history[-45:]
    plot_x = x + 9
    plot_y = y + 8
    plot_w = w - 15
    plot_h = h - 25
    bands = [
        (0, 29, RED_100),
        (30, 54, AMBER_100),
        (55, 69, BLUE_100),
        (70, 100, GREEN_100),
    ]
    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "B", 6.5)
    pdf.set_xy(x, y)
    pdf.cell(w, 4, "SCORE HISTORY WITH REGIME-COLORED OBSERVATIONS")

    for low, high, fill in bands:
        y_top = plot_y + plot_h - (high / 100) * plot_h
        band_h = ((high - low) / 100) * plot_h
        _set_color(pdf, fill, "fill")
        pdf.rect(plot_x, y_top, plot_w, band_h, style="F")
    _set_color(pdf, RULE, "draw")
    pdf.rect(plot_x, plot_y, plot_w, plot_h, style="D")

    pdf.set_font("DejaVu", "", 5.8)
    for tick in (0, 25, 50, 75, 100):
        ty = plot_y + plot_h - (tick / 100) * plot_h
        _set_color(pdf, RULE, "draw")
        pdf.line(plot_x, ty, plot_x + plot_w, ty)
        _set_color(pdf, INK_500)
        pdf.set_xy(x, ty - 1.8)
        pdf.cell(7, 3.5, str(tick), align="R")

    coords: list[tuple[float, float, HistoryPoint]] = []
    n = len(points)
    for idx, item in enumerate(points):
        px = plot_x + (plot_w * idx / max(1, n - 1))
        py = plot_y + plot_h - (max(0, min(100, item.score)) / 100) * plot_h
        coords.append((px, py, item))
    _set_color(pdf, BLUE, "draw")
    pdf.set_line_width(0.65)
    for (x0, y0, _), (x1, y1, _) in zip(coords, coords[1:]):
        pdf.line(x0, y0, x1, y1)
    pdf.set_line_width(0.2)
    for px, py, item in coords:
        _set_color(pdf, _regime_color(item.regime), "fill")
        _set_color(pdf, WHITE, "draw")
        pdf.ellipse(px - 1.25, py - 1.25, 2.5, 2.5, style="DF")

    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "", 5.8)
    pdf.set_xy(plot_x, plot_y + plot_h + 1.5)
    pdf.cell(36, 3.5, points[0].date.strftime("%d/%m/%Y"))
    pdf.set_xy(plot_x + plot_w - 36, plot_y + plot_h + 1.5)
    pdf.cell(36, 3.5, points[-1].date.strftime("%d/%m/%Y"), align="R")

    band_y = y + h - 9
    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "B", 5.8)
    pdf.set_xy(x, band_y - 4)
    pdf.cell(w, 3, "REGIME TIMELINE")
    bar_w = plot_w / len(points)
    for idx, item in enumerate(points):
        _set_color(pdf, _regime_color(item.regime), "fill")
        pdf.rect(plot_x + idx * bar_w, band_y, max(0.8, bar_w), 4.5, style="F")


def _page_cover(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    x = pdf.l_margin
    top_y = 17
    w = pdf.usable_w
    _set_color(pdf, NAVY, "fill")
    pdf.rect(x, top_y, w, 72, style="F")
    _set_color(pdf, (180, 195, 207))
    pdf.set_font("DejaVu", "B", 9)
    pdf.set_xy(x + 14, top_y + 21)
    pdf.cell(w - 28, 5, "INSTITUTIONAL MARKET RISK MONITOR")
    _set_color(pdf, WHITE)
    pdf.set_font("DejaVu", "B", 24)
    pdf.set_xy(x + 14, top_y + 40)
    pdf.cell(w - 28, 10, "VIETNAM EQUITY MARKET")
    pdf.set_font("DejaVu", "", 15)
    pdf.set_xy(x + 14, top_y + 56)
    pdf.cell(w - 28, 7, "AI CIO Executive Risk & Allocation Report")
    _set_color(pdf, TEAL, "fill")
    pdf.rect(x + 14, top_y + 74, 20, 3, style="F")

    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "B", 7)
    pdf.set_xy(x + 14, 103)
    pdf.cell(45, 4, "REPORTING DATE")
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 15)
    pdf.set_xy(x + 14, 109)
    pdf.cell(70, 6, model["display_date"])

    card_y = 129
    _set_color(pdf, WHITE, "fill")
    _set_color(pdf, RULE, "draw")
    pdf.rect(x + 12, card_y, w - 24, 48, style="DF")
    _set_color(pdf, INK_500)
    pdf.set_font("DejaVu", "B", 7)
    pdf.set_xy(x + 19, card_y + 9)
    pdf.cell(w - 38, 4, "DECISION REGIME")
    _set_color(pdf, _regime_color(model["regime"]))
    pdf.set_font("DejaVu", "B", 21)
    pdf.set_xy(x + 19, card_y + 20)
    pdf.multi_cell(w - 38, 8, model["regime"].upper())
    _set_color(pdf, INK_700)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.set_xy(x + 19, card_y + 37)
    pdf.cell(w - 38, 4, "Capital preservation and explicit risk-budget governance.")

    kpi_y = 186
    gap = 0.5
    card_w = (w - 24 - 3 * gap) / 4
    metrics = [
        ("Composite score", f"{model['score']:.0f} / 100", _score_color(model["score"]), SURFACE),
        ("Tail risk", model["tail_risk"], _status_color(model["tail_risk"]), _score_fill(40)),
        ("Confidence", model["confidence"], BLUE, BLUE_100),
        ("Primary horizon", model["horizon"], NAVY, SURFACE),
    ]
    for idx, (label, value, color, fill) in enumerate(metrics):
        _metric_card(pdf, x + 12 + idx * (card_w + gap), kpi_y, card_w, 31, label, value, "", color, fill)

    _set_color(pdf, INK_700)
    pdf.set_font("DejaVu", "", 7.3)
    pdf.set_xy(x + 14, 235)
    source_note = "Prepared from AI CIO source report, deterministic score ledger, and cached adapter metrics."
    if model.get("data_date"):
        source_note += f" Data date: {model['data_date']}."
    pdf.multi_cell(w - 28, 4, source_note)

    _set_color(pdf, NAVY, "fill")
    pdf.rect(x, 265, w, 18, style="F")
    _set_color(pdf, WHITE)
    pdf.set_font("DejaVu", "B", 6.6)
    pdf.set_xy(x + 14, 271)
    pdf.cell(w - 28, 4, CONFIDENTIALITY)


def _page_dashboard(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    _section_title(pdf, "01", "Executive Dashboard", "Decision-useful summary for Investment Committee review")
    x = pdf.l_margin
    y = pdf.get_y()
    _gauge(pdf, x + 22, y + 7, 49, float(model["score"]))
    text_x = x + 88
    _set_color(pdf, TEAL)
    pdf.set_font("DejaVu", "B", 6.8)
    pdf.set_xy(text_x, y + 7)
    pdf.cell(60, 4, "BASE CASE")
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 12.5)
    pdf.set_xy(text_x, y + 15)
    title = "Defensive positioning remains warranted." if float(model["score"]) < 45 else "Controlled risk budget remains warranted."
    pdf.multi_cell(78, 6.0, title)
    _set_color(pdf, INK)
    pdf.set_font("DejaVu", "", 7.6)
    pdf.set_xy(text_x, y + 29)
    pdf.multi_cell(78, 4.2, _shorten(model["summary"], 330))
    _set_color(pdf, _regime_color(model["regime"]))
    pdf.set_font("DejaVu", "B", 7.7)
    pdf.set_xy(text_x, min(pdf.get_y() + 1.5, y + 60))
    decision = "Decision: preserve capital; do not expand beta until hard constraints improve."
    if model["orders"]:
        decision = "Decision: " + "; ".join(
            f"{item['sleeve']} {item['target']} {item['instruction'].lower()}" for item in model["orders"][:3]
        )
    pdf.multi_cell(78, 4.1, _shorten(decision, 130))

    subs = model["subscores"]
    bar_y = y + 74
    _pillar_bar(pdf, x + 8, bar_y, 155, "Macro Risk", float(subs.get("macro_risk_score", model["score"])))
    _pillar_bar(pdf, x + 8, bar_y + 18, 155, "Market Internal", float(subs.get("market_internal_score", model["score"])))
    _pillar_bar(pdf, x + 8, bar_y + 36, 155, "Tail Risk", float(subs.get("tail_risk_score", model["score"])))

    strip_y = bar_y + 58
    strip_w = pdf.usable_w / 4
    strip_items = [
        ("Regime", model["regime"], "Hard baseline"),
        ("Tail risk", model["tail_risk"], "Warning taxonomy"),
        ("Confidence", model["confidence"], "Evidence quality"),
        ("Horizon", model["horizon"], "Primary window"),
    ]
    for idx, (label, value, sub) in enumerate(strip_items):
        color = _status_color(value)
        fill = _score_fill(25 if color == RED else 45 if color == AMBER else 60)
        _metric_card(pdf, x + idx * strip_w, strip_y, strip_w, 32, label, value.upper(), sub, color, fill)

    table_y = strip_y + 40
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, table_y - 7)
    pdf.cell(0, 5, "Critical Drivers")
    driver_rows = []
    for item in model["tool_scores"][:8]:
        score_txt = "DATA GAP" if item["score"] is None else f"{item['score']:.0f}/100"
        signal = item["bias"] or item["regime"]
        driver_rows.append([item["tool"], score_txt, signal.upper(), item["reason"]])
    if not driver_rows:
        driver_rows = [["DATA GAP", "-", "DATA GAP", "No structured adapter metrics found for this report date."]]
    _draw_table(
        pdf,
        x,
        table_y,
        pdf.usable_w,
        [("Indicator", 0.25), ("Reading", 0.16), ("Signal", 0.20), ("Investment implication", 0.39)],
        driver_rows,
        status_col=2,
        max_rows=6,
    )


def _page_history(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    _section_title(pdf, "02", "History & Regime Timeline", "Score persistence, recent deltas, and regime path through time")
    x = pdf.l_margin
    y = pdf.get_y()
    rolling = model["rolling"]
    kpis = [
        ("Today", f"{model['score']:.0f} / 100", f"Regime: {model['regime']}"),
        ("1-day change", f"{_safe_float(rolling.get('score_change_1d')) or 0:+.0f} pts", "Daily score delta"),
        ("5-day change", f"{_safe_float(rolling.get('score_change_5d')) or 0:+.0f} pts", "Momentum check"),
        ("Regime streak", f"{_safe_float(rolling.get('current_regime_streak')) or 0:.0f} days", "Current label run"),
    ]
    card_w = pdf.usable_w / 4
    for idx, (label, value, sub) in enumerate(kpis):
        color = _score_color(model["score"]) if idx == 0 else _status_color(value)
        fill = _score_fill(model["score"]) if idx == 0 else SURFACE
        _metric_card(pdf, x + idx * card_w, y, card_w, 28, label, value, sub, color, fill)
    _draw_history_chart(pdf, model["history"], x, y + 42, pdf.usable_w, 98)

    note_y = y + 151
    history_count = len(model["history"])
    source = "data_lake/Ai_cio_report.csv"
    note = (
        f"History rows used: {history_count}. Source: {source}. "
        "Malformed rows are ignored; if the selected report date is not in the ledger, the report score is appended in-memory for the chart only."
    )
    _callout(pdf, x, note_y, pdf.usable_w, "History use rule", note, BLUE, BLUE_100)

    reason_y = note_y + 36
    reasons = []
    for bucket in ("macro", "market_internal", "tail", "caps"):
        for item in model["score_band_reason"].get(bucket, [])[:3]:
            reasons.append(f"{bucket}: {item}")
    rows = [[item] for item in reasons[:4]]
    if rows:
        _set_color(pdf, NAVY)
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_xy(x, reason_y)
        pdf.cell(0, 5, "Score Band Evidence")
        _draw_table(pdf, x, reason_y + 8, pdf.usable_w, [("Evidence", 1.0)], rows, max_rows=4)


def _page_governance(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    _section_title(pdf, "03", "Portfolio Decision & Governance", "Orders, hard constraints, and data sufficiency boundaries")
    x = pdf.l_margin
    y = pdf.get_y()
    orders = model["orders"]
    if orders:
        rows = [[item["sleeve"], item["target"], item["instruction"], item["governance"]] for item in orders]
    else:
        rows = [["DATA GAP", "DATA GAP", "DATA GAP", "No explicit portfolio order block found in source report."]]
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, y)
    pdf.cell(0, 5, "Portfolio Orders")
    y = _draw_table(
        pdf,
        x,
        y + 8,
        pdf.usable_w,
        [("Sleeve", 0.24), ("Target", 0.15), ("Instruction", 0.21), ("Governance note", 0.40)],
        rows,
        status_col=2,
        max_rows=8,
    )

    y += 10
    constraints = model["hard_constraints"] or ["No hard-constraint sidecar found for this report date."]
    _callout(pdf, x, y, pdf.usable_w, "Discipline boundary", " ".join(constraints[:3]), RED if constraints else BLUE, RED_100 if constraints else BLUE_100)

    y = pdf.get_y() + 44
    rows = []
    for item in model["tool_scores"][:6]:
        score_txt = "DATA GAP" if item["score"] is None else f"{item['score']:.0f}"
        rows.append([item["tool"], score_txt, item["regime"], item["bias"], item["reason"]])
    if rows:
        _set_color(pdf, NAVY)
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_xy(x, y)
        pdf.cell(0, 5, "Hard Adapter Scorecard")
        _draw_table(
            pdf,
            x,
            y + 8,
            pdf.usable_w,
            [("Adapter", 0.20), ("Score", 0.10), ("Regime label", 0.26), ("Bias", 0.15), ("Reason", 0.29)],
            rows,
            status_col=3,
            max_rows=6,
        )


def _page_tail_consensus(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    _section_title(pdf, "04", "Tool Consensus & Tail Risk", "Hard adapters determine the decision; tail models set risk-budget brakes")
    x = pdf.l_margin
    y = pdf.get_y()
    w = pdf.usable_w

    tool_scores = model["tool_scores"]
    counts = {"bearish": 0, "neutral_or_mixed": 0, "bullish": 0}
    for item in tool_scores:
        bias = str(item.get("bias", "")).lower()
        if "bear" in bias:
            counts["bearish"] += 1
        elif "bull" in bias:
            counts["bullish"] += 1
        else:
            counts["neutral_or_mixed"] += 1

    card_w = w / 3
    consensus_cards = [
        ("Bearish hard signals", str(counts["bearish"]), "Risk-budget vetoes", RED, RED_100),
        ("Neutral / mixed", str(counts["neutral_or_mixed"]), "Context, not override", BLUE, BLUE_100),
        ("Bullish hard signals", str(counts["bullish"]), "Requires confirmation", GREEN, GREEN_100),
    ]
    for idx, (label, value, sub, color, fill) in enumerate(consensus_cards):
        _metric_card(pdf, x + idx * card_w, y, card_w, 26, label, value, sub, color, fill)

    y += 36
    rows = []
    for item in tool_scores[:6]:
        rows.append(
            [
                item["tool"].replace("_", " "),
                "DATA GAP" if item["score"] is None else f"{item['score']:.0f}",
                item["bias"].replace("_", " ").upper() or "DATA GAP",
                _shorten(item["regime"], 38),
                _shorten(item["reason"], 74),
            ]
        )
    if rows:
        _set_color(pdf, NAVY)
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_xy(x, y - 7)
        pdf.cell(0, 5, "Hard Adapter Scorecard")
        y = _draw_table(
            pdf,
            x,
            y,
            w,
            [("Adapter", 0.20), ("Score", 0.10), ("Bias", 0.15), ("Regime label", 0.24), ("Reason", 0.31)],
            rows,
            status_col=2,
            max_rows=6,
        )

    metrics_tools = model.get("metrics_tools", {})
    y += 12
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, y - 5)
    pdf.cell(0, 5, "Tail Risk Audit")
    tail_y = y + 4
    gap = 4
    box_w = (w - gap) / 2
    box_h = 31

    tail_cards = [
        (
            "ESR / SSI",
            f"{_fmt_number(_metric_value(metrics_tools, 'esr_monitor', 'ssi_pct'), '%')} - WARNING",
            _tool_payload(metrics_tools, "esr_monitor").get("score_reason", "Systemic stress adapter"),
            AMBER,
            AMBER_100,
        ),
        (
            "EVT",
            f"xi {_fmt_number(_metric_value(metrics_tools, 'var_cvar_vnindex', 'evt_xi'), '', 3)}",
            _tool_payload(metrics_tools, "var_cvar_vnindex").get("score_reason", "Tail-index sensitivity disclosure"),
            AMBER,
            AMBER_100,
        ),
        (
            "ABM",
            f"Yellow / {_fmt_number(_metric_value(metrics_tools, 'abm_simulator', 'abm_early_warning_score'), '/100')}",
            _tool_payload(metrics_tools, "abm_simulator").get("score_reason", "Agent-based fragility watch"),
            AMBER,
            AMBER_100,
        ),
        (
            "VaRES",
            "Soft evidence",
            "No hard adapter score available in the metrics snapshot; use as secondary context.",
            BLUE,
            BLUE_100,
        ),
    ]
    for idx, (label, value, body, color, fill) in enumerate(tail_cards):
        bx = x + (idx % 2) * (box_w + gap)
        by = tail_y + (idx // 2) * (box_h + gap)
        _metric_card(pdf, bx, by, box_w, box_h, label, value, _shorten(body, 88), color, fill)

    y = tail_y + 2 * box_h + gap + 12
    verdict = (
        f"Tail risk is classified as {model['tail_risk']}. "
        "Risk budget remains constrained until breadth, domestic funding and ABM/SSI indicators improve together."
    )
    _callout(pdf, x, y, w, "Tail-risk verdict", verdict, AMBER, AMBER_100)


def _page_monitoring(pdf: _AiCioPDF, model: dict[str, Any]) -> None:
    pdf.add_page()
    _section_title(pdf, "05", "Monitoring & Final Decision", "Implementation controls, data limitations and gating conditions")
    x = pdf.l_margin
    y = pdf.get_y()
    w = pdf.usable_w

    rows = [
        ["Daily", "VNIBOR ON and LTMM transmission", "Confirm domestic funding stress is easing"],
        ["Daily", "Breadth MA20 / MA60 participation", "Look for broad participation recovery"],
        ["Daily", "SSI and ABM yellow/orange state", "Escalate if stress migrates from warning to critical"],
        ["Weekly", "Fed liquidity and Global FCI", "Separate upstream impulse from domestic transmission"],
        ["Monthly", "VN100 cash-confirmation metrics", "Check whether accounting recovery becomes cash-supported"],
    ]
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, y)
    pdf.cell(0, 5, "Monitoring Checklist")
    y = _draw_table(
        pdf,
        x,
        y + 8,
        w,
        [("Cadence", 0.16), ("Monitor", 0.38), ("Decision use", 0.46)],
        rows,
        max_rows=5,
    )

    y += 12
    gaps = model.get("data_gaps") or [
        "No explicit data gaps were parsed from the source report; rely on adapter data-quality flags where available."
    ]
    gap_rows = [[_shorten(item, 140), "DATA GAP" if "DATA" in item.upper() else "WATCH"] for item in gaps[:5]]
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, y)
    pdf.cell(0, 5, "Data Sufficiency")
    y = _draw_table(
        pdf,
        x,
        y + 8,
        w,
        [("Area / limitation", 0.78), ("Status", 0.22)],
        gap_rows,
        status_col=1,
        max_rows=5,
    )

    y += 12
    disclosures = [
        "This report formats supplied AI CIO outputs and deterministic cached metrics; it is not independent market-data validation.",
        "Model labels such as PRE-CRASH / PANIC are framework-specific indicators, not certain forecasts.",
        "Portfolio instructions require human governance review before implementation.",
        "Missing inputs are shown as data gaps and should not be inferred as zero.",
    ]
    _set_color(pdf, NAVY)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_xy(x, y)
    pdf.cell(0, 5, "Important Disclosures")
    pdf.set_y(y + 8)
    _set_color(pdf, INK)
    pdf.set_font("DejaVu", "", 7.2)
    for item in disclosures:
        line_y = pdf.get_y()
        pdf.set_xy(x, line_y)
        _set_color(pdf, TEAL)
        pdf.cell(3, 3.8, "-")
        _set_color(pdf, INK)
        pdf.set_xy(x + 4, line_y)
        pdf.multi_cell(w - 4, 3.8, item)
        pdf.ln(0.8)

    if model["orders"]:
        stance = "; ".join(
            f"{item['sleeve']} {item['target']} {item['instruction'].lower()}" for item in model["orders"][:3]
        )
    else:
        stance = "capital preservation until hard constraints improve"
    final = (
        f"Composite score {model['score']:.0f} / 100. Regime: {model['regime']}. "
        f"Primary stance: {stance}."
    )
    _callout(pdf, x, 238, w, "Final decision", final, NAVY, SURFACE)


def create_ai_cio_pdf(
    report_text: str,
    path: str | Path,
    report_date: str | date | None = None,
    provider_key: str = "",
    data_lake: Path = DATA_LAKE,
    root_dir: Path = ROOT_DIR,
) -> Path:
    """Create an institutional AI CIO PDF with score history and regime timeline."""
    try:
        from shared.ai_cio import strip_wrapping_markdown_fence

        report_text = strip_wrapping_markdown_fence(str(report_text or ""))
    except Exception:
        report_text = str(report_text or "")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    parsed_date = _parse_report_date(report_date)
    model = _build_model(report_text, parsed_date, provider_key, data_lake)

    pdf = _AiCioPDF(root_dir)
    _page_cover(pdf, model)
    _page_dashboard(pdf, model)
    _page_history(pdf, model)
    _page_governance(pdf, model)
    _page_tail_consensus(pdf, model)
    _page_monitoring(pdf, model)
    pdf.output(str(target))
    return target
