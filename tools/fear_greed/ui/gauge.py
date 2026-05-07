import streamlit as st
import plotly.graph_objects as go
from config import SCORE_BANDS

_BAR_COLORS = {
    "EXTREME FEAR":  "crimson",
    "FEAR":          "orangered",
    "STOCK PICKING": "gray",
    "GREED":         "yellowgreen",
    "EXTREME GREED": "seagreen",
}


def _classify(score: float) -> tuple:
    for lo, hi, bg, label in SCORE_BANDS:
        if lo <= score < hi or (score >= 100 and hi == 100):
            return label, _BAR_COLORS[label]
    return "EXTREME GREED", "seagreen"


def render_gauge(score: float) -> None:
    label, bar_color = _classify(score)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": f"<b>{label}</b>", "font": {"size": 18}},
        gauge={
            "axis":      {"range": [0, 100], "tickwidth": 1, "tickcolor": "darkblue"},
            "bar":       {"color": bar_color},
            "steps":     [{"range": [lo, hi], "color": bg} for lo, hi, bg, _ in SCORE_BANDS],
            "threshold": {"line": {"color": "black", "width": 4},
                          "thickness": 0.75, "value": score},
        },
    ))
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=60, b=10))
    st.plotly_chart(fig, use_container_width=True)
