from __future__ import annotations

import pandas as pd
import plotly.express as px

from tools.bank_valuation.quant.summary import (
    CLASSIFICATION_LABELS_VI,
    eligible_valuation_data,
)


CLASSIFICATION_COLORS = {
    "Strong Undervalued": "#15803d",
    "Undervalued but Risky": "#65a30d",
    "Fairly Valued": "#64748b",
    "Overvalued": "#b91c1c",
    "Value Trap Warning": "#d97706",
    "Neutral / Need More Data": "#475569",
}


def plot_classification_breadth(summary: pd.DataFrame):
    chart = summary[summary["count"] > 0].copy()
    if chart.empty:
        return None
    fig = px.bar(
        chart,
        x="label_vi",
        y="count",
        text="count",
        color="classification",
        color_discrete_map=CLASSIFICATION_COLORS,
        custom_data=["share"],
    )
    fig.update_traces(
        textposition="outside",
        hovertemplate="%{x}<br>Số mã: %{y}<br>Tỷ trọng: %{customdata[0]:.1%}<extra></extra>",
    )
    fig.update_layout(
        title="Phân bổ kết luận định giá",
        xaxis_title="",
        yaxis_title="Số mã",
        height=360,
        showlegend=False,
        margin=dict(l=10, r=10, t=55, b=30),
    )
    return fig


def plot_valuation_gap(data: pd.DataFrame):
    result = eligible_valuation_data(data)
    if result.empty or "valuation_gap_pct" not in result.columns:
        return None
    result = result.copy()
    result["valuation_gap_pct"] = pd.to_numeric(result["valuation_gap_pct"], errors="coerce") * 100
    result = result.dropna(subset=["valuation_gap_pct", "ticker"])
    if result.empty:
        return None
    result["classification_vi"] = result["classification"].map(CLASSIFICATION_LABELS_VI).fillna(result["classification"])
    result = result.sort_values("valuation_gap_pct")

    fig = px.bar(
        result,
        x="ticker",
        y="valuation_gap_pct",
        color="classification",
        color_discrete_map=CLASSIFICATION_COLORS,
        hover_data={
            "ticker": True,
            "valuation_gap_pct": ":.1f",
            "classification_vi": True,
            "classification": False,
        },
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#64748b", opacity=0.7)
    fig.update_layout(
        title="Khoảng cách định giá theo ngân hàng",
        xaxis_title="Mã",
        yaxis_title="Gap định giá (%)",
        height=430,
        legend_title_text="Kết luận",
        margin=dict(l=10, r=10, t=55, b=40),
    )
    return fig


def plot_gap_vs_risk(data: pd.DataFrame):
    result = eligible_valuation_data(data)
    required = {"valuation_gap_pct", "overall_risk_score", "ticker"}
    if result.empty or not required.issubset(result.columns):
        return None
    result = result.copy()
    result["valuation_gap_pct"] = pd.to_numeric(result["valuation_gap_pct"], errors="coerce") * 100
    result["overall_risk_score"] = pd.to_numeric(result["overall_risk_score"], errors="coerce")
    result = result.dropna(subset=["valuation_gap_pct", "overall_risk_score"])
    if result.empty:
        return None

    fig = px.scatter(
        result,
        x="valuation_gap_pct",
        y="overall_risk_score",
        text="ticker",
        color="classification",
        color_discrete_map=CLASSIFICATION_COLORS,
        size=pd.to_numeric(result.get("confidence_score", 60), errors="coerce").fillna(60),
        hover_data=["ticker", "period", "market_pb", "justified_pb", "data_quality_flag"],
    )
    fig.add_vline(x=0, line_dash="dash", line_color="#64748b", opacity=0.7)
    fig.add_hline(y=50, line_dash="dash", line_color="#64748b", opacity=0.7)
    fig.update_traces(textposition="top center")
    fig.update_layout(
        title="Gap định giá vs rủi ro tổng hợp",
        xaxis_title="Gap định giá (%)",
        yaxis_title="Risk score",
        height=470,
        legend_title_text="Kết luận",
        margin=dict(l=10, r=10, t=55, b=40),
    )
    return fig


def plot_market_confirmation(data: pd.DataFrame):
    result = eligible_valuation_data(data)
    required = {"valuation_gap_pct", "market_confirmation_score", "ticker"}
    if result.empty or not required.issubset(result.columns):
        return None
    result = result.copy()
    result["valuation_gap_pct"] = pd.to_numeric(result["valuation_gap_pct"], errors="coerce") * 100
    result["market_confirmation_score"] = pd.to_numeric(result["market_confirmation_score"], errors="coerce")
    result = result.dropna(subset=["valuation_gap_pct", "market_confirmation_score"])
    if result.empty:
        return None

    fig = px.scatter(
        result,
        x="valuation_gap_pct",
        y="market_confirmation_score",
        text="ticker",
        color="classification",
        color_discrete_map=CLASSIFICATION_COLORS,
        hover_data=["ticker", "market_confirmation_label", "return_20d", "return_60d", "drawdown_60d"],
    )
    fig.add_vline(x=0, line_dash="dash", line_color="#64748b", opacity=0.7)
    fig.add_hline(y=50, line_dash="dash", line_color="#64748b", opacity=0.7)
    fig.update_traces(textposition="top center")
    fig.update_layout(
        title="Gap định giá vs xác nhận giá",
        xaxis_title="Gap định giá (%)",
        yaxis_title="Market confirmation score",
        height=430,
        legend_title_text="Kết luận",
        margin=dict(l=10, r=10, t=55, b=40),
    )
    return fig
