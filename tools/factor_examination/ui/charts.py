"""
charts.py — Plotly charts cho Factor Examination tool.

NO business logic — chỉ render. Pure presentation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots


# ── Tab 1: Universe Ranking ──────────────────────────────────
def render_factor_heatmap(z_table: pd.DataFrame, tickers: list[str], title: str) -> go.Figure:
    """Heatmap row=ticker col=factor color=z-score. Diverging colormap."""
    sub = z_table.loc[tickers]
    fig = go.Figure(data=go.Heatmap(
        z=sub.values,
        x=sub.columns.tolist(),
        y=sub.index.tolist(),
        colorscale="RdYlGn",
        zmid=0,
        zmin=-2.5, zmax=2.5,
        text=sub.round(2).values,
        texttemplate="%{text}",
        textfont={"size": 9},
        colorbar=dict(title="z-score"),
        hovertemplate="Ticker: %{y}<br>Factor: %{x}<br>z: %{z:.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        height=max(350, 20 * len(tickers) + 100),
        margin=dict(l=10, r=10, t=70, b=10),
        xaxis=dict(side="top"),
    )
    return fig


def render_decile_distribution(composite: pd.Series) -> go.Figure:
    """Histogram + decile boundary lines."""
    valid = composite.dropna()
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=valid.values,
        nbinsx=30,
        marker=dict(color="steelblue", line=dict(color="white", width=1)),
        hovertemplate="Composite z: %{x:.2f}<br>Count: %{y}<extra></extra>",
    ))
    for q in (0.1, 0.5, 0.9):
        v = valid.quantile(q)
        fig.add_vline(x=v, line=dict(color="red" if q in (0.1, 0.9) else "gray", dash="dash"),
                      annotation_text=f"p{int(q*100)}={v:.2f}", annotation_position="top")
    fig.update_layout(
        title="Composite score distribution (universe)",
        xaxis_title="Composite z-score",
        yaxis_title="Count",
        height=380,
        margin=dict(l=10, r=10, t=60, b=40),
        showlegend=False,
    )
    return fig


def render_sector_composition(
    top_tickers: list[str],
    bot_tickers: list[str],
    sector_map: pd.Series,
) -> go.Figure:
    """Stacked bar: top decile sector composition vs bot decile."""
    top_sec = sector_map.reindex(top_tickers).fillna("Other").value_counts()
    bot_sec = sector_map.reindex(bot_tickers).fillna("Other").value_counts()

    all_sectors = sorted(set(top_sec.index) | set(bot_sec.index))
    top_vals = [top_sec.get(s, 0) for s in all_sectors]
    bot_vals = [bot_sec.get(s, 0) for s in all_sectors]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Top decile (mạnh)", x=all_sectors, y=top_vals, marker_color="#2ca02c"))
    fig.add_trace(go.Bar(name="Bottom decile (yếu)", x=all_sectors, y=bot_vals, marker_color="#d62728"))
    fig.update_layout(
        title="Sector composition: top vs bottom decile",
        barmode="group",
        height=380,
        margin=dict(l=10, r=10, t=60, b=80),
        xaxis=dict(tickangle=-30),
    )
    return fig


# ── Tab 2: Portfolio Examination ────────────────────────────
def render_factor_radar(
    portfolio_exposure: pd.Series,
    benchmark_exposure: pd.Series | None = None,
) -> go.Figure:
    """Radar (spider) chart 10 chiều portfolio vs benchmark."""
    factors = portfolio_exposure.index.tolist()
    p_vals = portfolio_exposure.fillna(0).values.tolist()
    # Close polygon
    factors_closed = factors + [factors[0]]
    p_vals_closed = p_vals + [p_vals[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=p_vals_closed, theta=factors_closed,
        fill="toself", name="Portfolio",
        line=dict(color="#1f77b4", width=2),
    ))
    if benchmark_exposure is not None:
        b_vals = benchmark_exposure.fillna(0).reindex(factors).values.tolist()
        b_closed = b_vals + [b_vals[0]]
        fig.add_trace(go.Scatterpolar(
            r=b_closed, theta=factors_closed,
            fill="toself", name="Benchmark (equal-weight universe)",
            line=dict(color="gray", width=1, dash="dot"),
            opacity=0.4,
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[-1.5, 1.5], dtick=0.5),
        ),
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        title="Factor exposure portfolio vs benchmark",
        showlegend=True,
    )
    return fig


def render_holdings_table_chart(holdings_table: pd.DataFrame) -> go.Figure:
    """Horizontal bar: composite z per holding, color theo rank quartile."""
    df = holdings_table.copy().sort_values("composite_z")
    colors = []
    for r in df["rank_pct"]:
        if pd.isna(r):
            colors.append("lightgray")
        elif r >= 75:
            colors.append("#2ca02c")
        elif r <= 25:
            colors.append("#d62728")
        else:
            colors.append("#7f7f7f")
    fig = go.Figure(go.Bar(
        x=df["composite_z"],
        y=df["ticker"],
        orientation="h",
        marker_color=colors,
        text=df["rank_pct"].apply(lambda x: f"p{x:.0f}" if pd.notna(x) else ""),
        textposition="outside",
        hovertemplate=(
            "Ticker: %{y}<br>Composite z: %{x:.2f}<br>"
            "Weight: %{customdata[0]:.1%}<br>Sector: %{customdata[1]}<extra></extra>"
        ),
        customdata=df[["weight", "sector"]].values,
    ))
    fig.update_layout(
        title="Holdings ranked by composite z (green = top quartile, red = bottom)",
        xaxis_title="Composite z-score",
        height=max(300, 24 * len(df) + 100),
        margin=dict(l=10, r=10, t=60, b=40),
    )
    return fig


# ── Tab 3: Ticker Profile ───────────────────────────────────
def render_ticker_factor_bar(z_row: pd.Series, ticker: str) -> go.Figure:
    """Bar chart factor z-score của 1 ticker, color sign."""
    s = z_row.dropna()
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in s.values]
    fig = go.Figure(go.Bar(
        x=s.index, y=s.values, marker_color=colors,
        text=[f"{v:+.2f}" for v in s.values],
        textposition="outside",
    ))
    fig.update_layout(
        title=f"{ticker} — factor z-scores (sector-neutral)",
        yaxis=dict(title="z-score", range=[-3.2, 3.2], zeroline=True),
        height=400,
        margin=dict(l=10, r=10, t=60, b=40),
    )
    fig.add_hline(y=1, line=dict(color="green", dash="dot"), opacity=0.4)
    fig.add_hline(y=-1, line=dict(color="red", dash="dot"), opacity=0.4)
    return fig


# ── Tab 4: IC Validation ────────────────────────────────────
def render_ic_timeseries(ic_series: pd.DataFrame) -> go.Figure:
    """IC theo thời gian + horizontal mean line per horizon."""
    fig = make_subplots(rows=len(ic_series.columns), cols=1, shared_xaxes=True,
                        subplot_titles=[c.replace("ic_", "IC ").upper() for c in ic_series.columns],
                        vertical_spacing=0.08)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
    for i, col in enumerate(ic_series.columns):
        s = ic_series[col]
        color = colors[i % len(colors)]
        fig.add_trace(
            go.Bar(x=s.index, y=s.values, marker_color=color, name=col,
                   hovertemplate="Date: %{x|%Y-%m-%d}<br>IC: %{y:.3f}<extra></extra>"),
            row=i + 1, col=1,
        )
        mean_v = s.mean()
        if pd.notna(mean_v):
            fig.add_hline(y=mean_v, line=dict(color=color, dash="dash"),
                          row=i + 1, col=1,
                          annotation_text=f"mean={mean_v:.3f}", annotation_position="right")
        fig.add_hline(y=0, line=dict(color="black", dash="solid", width=0.5),
                      row=i + 1, col=1)
    fig.update_layout(
        height=180 * len(ic_series.columns) + 80,
        margin=dict(l=10, r=10, t=60, b=40),
        showlegend=False,
        title="Spearman IC time series — composite vs forward return",
    )
    return fig


def render_decile_cum(decile_df: pd.DataFrame) -> go.Figure:
    """Cumulative top decile vs bot decile (21d holding period)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=decile_df.index, y=decile_df["top_cum"],
        mode="lines", name="Top 10% composite",
        line=dict(color="#2ca02c", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=decile_df.index, y=decile_df["bot_cum"],
        mode="lines", name="Bottom 10% composite",
        line=dict(color="#d62728", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=decile_df.index, y=decile_df["spread_cum"],
        mode="lines", name="Spread (top - bot)",
        line=dict(color="#1f77b4", width=2, dash="dash"),
        yaxis="y2",
    ))
    fig.update_layout(
        title="Decile cumulative (21d forward, snapshot monthly)",
        xaxis_title="Snapshot date",
        yaxis=dict(title="Cumulative growth (1 = start)"),
        yaxis2=dict(title="Spread", overlaying="y", side="right"),
        height=420,
        margin=dict(l=10, r=10, t=60, b=40),
        hovermode="x unified",
    )
    return fig
