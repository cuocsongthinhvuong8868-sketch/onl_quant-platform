import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def render_analysis_chart(scored_df: pd.DataFrame) -> None:
    """
    3-panel chart:
    Panel 1: Market Factor (bar) + EGARCH Vol (line, trục phải)
    Panel 2: Downside/Upside Corr (trái) + Kelly Skewness (phải)
    Panel 3: Cross-Sectional Volatility (filled area)
    """
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": False}]],
        subplot_titles=(
            "1. Market Factor (PCA) vs EGARCH Volatility",
            "2. Rủi ro Đuôi — Directional Correlations & Kelly Skewness",
            "3. Cross-Sectional Volatility Index (CSV)",
        ),
    )

    bar_colors = ["seagreen" if v > 0 else "crimson" for v in scored_df["Market_Factor"]]
    fig.add_trace(go.Bar(
        x=scored_df.index, y=scored_df["Market_Factor"],
        name="Market Factor", marker_color=bar_colors, opacity=0.55,
    ), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=scored_df.index, y=scored_df["EGARCH_Vol"],
        name="EGARCH Vol", line=dict(color="purple", width=2),
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=scored_df.index, y=scored_df["Downside_Corr"],
        name="Downside Corr", line=dict(color="crimson", width=1.5),
    ), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=scored_df.index, y=scored_df["Upside_Corr"],
        name="Upside Corr", line=dict(color="seagreen", width=1.5),
    ), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=scored_df.index, y=scored_df["Skewness"],
        name="Kelly Skewness", line=dict(color="black", dash="dot"),
    ), row=2, col=1, secondary_y=True)

    csv_pct = np.sqrt(scored_df["CSV_Index"]) * 100
    fig.add_trace(go.Scatter(
        x=scored_df.index, y=csv_pct,
        name="CSV (%)", line=dict(color="royalblue", width=2),
        fill="tozeroy", fillcolor="rgba(65,105,225,0.12)",
    ), row=3, col=1)

    fig.update_yaxes(title_text="Return (%)",    tickformat=".1%", row=1, col=1, secondary_y=False,
                     title_font=dict(color="seagreen"), tickfont=dict(color="seagreen"))
    fig.update_yaxes(title_text="EGARCH Vol",    tickformat=".1%", row=1, col=1, secondary_y=True,
                     title_font=dict(color="purple"),   tickfont=dict(color="purple"))
    fig.update_yaxes(title_text="Correlation",   row=2, col=1, secondary_y=False,
                     title_font=dict(color="crimson"),  tickfont=dict(color="crimson"))
    fig.update_yaxes(title_text="Kelly Skewness",row=2, col=1, secondary_y=True,
                     title_font=dict(color="black"),    tickfont=dict(color="black"))
    fig.update_yaxes(title_text="CSV Vol (%)",   tickformat=".1f", row=3, col=1,
                     title_font=dict(color="royalblue"),tickfont=dict(color="royalblue"))

    fig.update_layout(
        height=880, hovermode="x unified",
        margin=dict(l=60, r=60, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
