from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st


TONE_STYLES = {
    "positive": {
        "text": "#15803d",
        "border": "#22c55e",
        "bg": "#f0fdf4",
        "soft": "#dcfce7",
    },
    "warning": {
        "text": "#b45309",
        "border": "#f59e0b",
        "bg": "#fffbeb",
        "soft": "#fef3c7",
    },
    "danger": {
        "text": "#b91c1c",
        "border": "#ef4444",
        "bg": "#fef2f2",
        "soft": "#fee2e2",
    },
    "info": {
        "text": "#1d4ed8",
        "border": "#3b82f6",
        "bg": "#eff6ff",
        "soft": "#dbeafe",
    },
    "neutral": {
        "text": "#334155",
        "border": "#94a3b8",
        "bg": "#f8fafc",
        "soft": "#e2e8f0",
    },
}


GLOBAL_STYLE = """
<style>
.block-container {
    max-width: 96rem;
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

div[data-testid="stMetric"] {
    min-height: 70px;
    overflow: visible;
}
div[data-testid="stMetric"] label,
div[data-testid="stMetric"] [data-testid="stMetricLabel"],
div[data-testid="stMetric"] [data-testid="stMetricValue"],
div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    max-width: 100%;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    overflow-wrap: anywhere;
    word-break: break-word;
    line-height: 1.25;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] > div,
div[data-testid="stMetric"] [data-testid="stMetricDelta"] > div {
    white-space: normal !important;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.oq-signal-card {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--oq-signal-border);
    border-left: 6px solid var(--oq-signal-border);
    border-radius: 8px;
    padding: 0.72rem 0.84rem;
    min-height: var(--oq-signal-min-height, 82px);
    background: var(--oq-signal-bg);
    overflow: visible;
}
.oq-signal-label {
    color: #475569;
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 0.34rem;
    white-space: normal;
    overflow-wrap: anywhere;
}
.oq-signal-value {
    display: block;
    color: var(--oq-signal-text);
    font-size: 1.08rem;
    font-weight: 760;
    line-height: 1.24;
    white-space: normal;
    overflow: visible;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.oq-signal-caption {
    margin-top: 0.4rem;
    color: #64748b;
    font-size: 0.82rem;
    line-height: 1.28;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.oq-signal-pill {
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    box-sizing: border-box;
    padding: 0.18rem 0.52rem;
    border-radius: 999px;
    border: 1px solid var(--oq-signal-border);
    background: var(--oq-signal-soft);
    color: var(--oq-signal-text);
    font-size: 0.82rem;
    font-weight: 700;
    line-height: 1.24;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
</style>
"""


def setup_page(page_title: str) -> None:
    st.set_page_config(
        page_title=page_title,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(GLOBAL_STYLE, unsafe_allow_html=True)


def tone_for_signal(value: Any, default: str = "neutral") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default

    danger_words = (
        "stress", "critical", "cut", "tight", "pre-crash", "high stress",
        "đảo ngược", "rủi ro", "risk", "fire", "falsified", "bearish",
    )
    warning_words = (
        "warning", "elevated", "watch", "alert", "cảnh báo", "thắt chặt",
        "cao", "bẫy", "coupling", "anchoring", "leverage",
    )
    positive_words = (
        "add", "calm", "easy", "safe", "healthy", "accommodative",
        "low stress", "bình thường", "dốc lên", "dồi dào", "tích lũy",
        "tăng trưởng", "normal",
    )
    neutral_words = ("hold", "neutral", "trung tính", "sideway", "status quo", "monitor")

    if any(word in text for word in danger_words):
        return "danger"
    if any(word in text for word in warning_words):
        return "warning"
    if any(word in text for word in positive_words):
        return "positive"
    if any(word in text for word in neutral_words):
        return "neutral"
    return default


def _tone_style(tone: str | None, value: Any = None) -> dict[str, str]:
    resolved = tone or tone_for_signal(value)
    return TONE_STYLES.get(resolved, TONE_STYLES["neutral"])


def _style_vars(style: dict[str, str], min_height: int) -> str:
    return (
        f"--oq-signal-text:{style['text']};"
        f"--oq-signal-border:{style['border']};"
        f"--oq-signal-bg:{style['bg']};"
        f"--oq-signal-soft:{style['soft']};"
        f"--oq-signal-min-height:{int(min_height)}px;"
    )


def signal_card_html(
    label: Any,
    value: Any,
    *,
    tone: str | None = None,
    icon: str = "",
    caption: Any | None = None,
    min_height: int = 82,
) -> str:
    style = _tone_style(tone, value)
    label_text = escape(str(label))
    icon_text = f"{escape(str(icon))} " if icon else ""
    value_text = escape(str(value))
    caption_html = ""
    if caption is not None and str(caption).strip():
        caption_html = f'<div class="oq-signal-caption">{escape(str(caption))}</div>'
    return (
        f'<div class="oq-signal-card" style="{_style_vars(style, min_height)}">'
        f'<div class="oq-signal-label">{label_text}</div>'
        f'<div class="oq-signal-value">{icon_text}{value_text}</div>'
        f"{caption_html}"
        f"</div>"
    )


def render_signal_card(
    label: Any,
    value: Any,
    *,
    tone: str | None = None,
    icon: str = "",
    caption: Any | None = None,
    min_height: int = 82,
) -> None:
    st.markdown(
        signal_card_html(
            label,
            value,
            tone=tone,
            icon=icon,
            caption=caption,
            min_height=min_height,
        ),
        unsafe_allow_html=True,
    )


def signal_pill_html(value: Any, *, tone: str | None = None, icon: str = "") -> str:
    style = _tone_style(tone, value)
    icon_text = f"{escape(str(icon))} " if icon else ""
    return (
        f'<span class="oq-signal-pill" style="{_style_vars(style, 0)}">'
        f"{icon_text}{escape(str(value))}"
        f"</span>"
    )
