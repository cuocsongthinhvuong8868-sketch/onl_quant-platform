"""Plotly figures for the Vietnam corporate credit-spread monitor."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


COLORS = {
    "bank": "#0F766E",
    "real_estate": "#C2410C",
    "widening": "#B42318",
    "narrowing": "#15803D",
    "unchanged": "#64748B",
    "government": "#475569",
}


def plot_yields_and_spread(spread: pd.DataFrame) -> go.Figure:
    """Two-row view of sector yields and the positive BDS risk premium."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.11,
        row_heights=[0.58, 0.42],
        subplot_titles=("Lãi suất phát hành", "Phần bù rủi ro BĐS so với Bank (Spread)"),
    )
    fig.add_trace(
        go.Scatter(
            x=spread.index,
            y=spread["bank_yield_pct"],
            name="Bank",
            mode="lines+markers",
            line={"color": COLORS["bank"], "width": 2.4},
            marker={"size": 7},
            hovertemplate="%{x|%d/%m/%Y}<br>Bank: %{y:.2f}%<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=spread.index,
            y=spread["real_estate_yield_pct"],
            name="Bất động sản",
            mode="lines+markers",
            line={"color": COLORS["real_estate"], "width": 2.4},
            marker={"size": 7, "symbol": "square"},
            hovertemplate="%{x|%d/%m/%Y}<br>BĐS: %{y:.2f}%<extra></extra>",
        ),
        row=1,
        col=1,
    )

    marker_colors = spread["direction"].map(
        {
            "WIDENING": COLORS["widening"],
            "NARROWING": COLORS["narrowing"],
            "UNCHANGED": COLORS["unchanged"],
            "N/A": COLORS["unchanged"],
        }
    )
    fig.add_trace(
        go.Scatter(
            x=spread.index,
            y=spread["risk_premium_bps"],
            name="BĐS - Bank",
            mode="lines+markers",
            line={"color": COLORS["real_estate"], "width": 2.4},
            marker={"color": marker_colors, "size": 8},
            customdata=spread[["signed_spread_pct", "spread_return_pct"]],
            hovertemplate=(
                "%{x|%d/%m/%Y}<br>Risk premium: %{y:.0f} bps"
                "<br>Bank - BĐS: %{customdata[0]:+.2f} điểm %"
                "<br>Return: %{customdata[1]:+.1f}%<extra></extra>"
            ),
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line_color="#94A3B8", line_width=1, row=2, col=1)
    fig.update_yaxes(title_text="Lãi suất (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text="Basis points", ticksuffix=" bps", row=2, col=1)
    fig.update_xaxes(title_text="Ngày báo cáo", row=2, col=1)
    fig.update_layout(
        height=650,
        margin={"l": 20, "r": 20, "t": 70, "b": 25},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.08, "x": 0},
    )
    return fig


def plot_latest_benchmark(latest: pd.DataFrame) -> go.Figure:
    """Compare latest sector spreads over matched government-tenor proxies."""
    plot = latest.copy()
    plot["label"] = plot["maturity_bucket"].map(
        {"<=3Y": "≤3Y / TPCP 3Y", "3Y_5Y": "3-5Y / TPCP 5Y", ">5Y": ">5Y / TPCP 10Y"}
    ).fillna(plot["maturity_bucket"])
    plot["sector_label"] = plot["sector"].map({"bank": "Bank", "real_estate": "Bất động sản"})

    fig = go.Figure()
    for sector, color in (("bank", COLORS["bank"]), ("real_estate", COLORS["real_estate"])):
        rows = plot.loc[plot["sector"].eq(sector)]
        fig.add_trace(
            go.Bar(
                x=rows["label"],
                y=rows["government_spread_bps"],
                name="Bank" if sector == "bank" else "Bất động sản",
                marker_color=color,
                customdata=rows[["yield_avg_pct", "government_yield_pct", "report_date"]],
                hovertemplate=(
                    "%{x}<br>Spread/TPCP: %{y:.0f} bps"
                    "<br>Corp yield: %{customdata[0]:.2f}%"
                    "<br>TPCP: %{customdata[1]:.2f}%"
                    "<br>Kỳ báo cáo: %{customdata[2]|%d/%m/%Y}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_color="#94A3B8", line_width=1)
    fig.update_layout(
        height=440,
        barmode="group",
        bargap=0.25,
        margin={"l": 20, "r": 20, "t": 40, "b": 25},
        xaxis_title="Kỳ hạn doanh nghiệp / tenor TPCP proxy",
        yaxis_title="Spread so với TPCP (bps)",
        legend={"orientation": "h", "y": 1.1, "x": 0},
    )
    return fig
