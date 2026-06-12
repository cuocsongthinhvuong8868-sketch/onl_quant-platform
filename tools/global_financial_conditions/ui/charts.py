"""
tools/global_financial_conditions/ui/charts.py
Plotly charts cho GFCM (Tab 1 = Level, Tab 2 = Analytics).

11 indicators chia 3 nhóm:
  Volatility (5):  VIX, MOVE, SKEW, OVX, VVIX
  Credit     (4):  HY_OAS, CCC_OAS, IG_OAS, EM_OAS
  Macro      (2):  T10Y2Y, DXY

PCA core 6 series (panel percentile): VIX, MOVE, SKEW, HY, CCC, IG.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

REGIME_COLOR = {
    "STRESS": "#dc2626",
    "ELEVATED": "#f59e0b",
    "CALM": "#16a34a",
    "N/A": "#cbd5e1",
}

SERIES_COLOR = {
    # Volatility
    "VIX": "#0284c7",
    "MOVE": "#7c3aed",
    "SKEW": "#0ea5e9",
    "OVX": "#65a30d",
    "VVIX": "#0891b2",
    # Credit
    "HY_OAS": "#f59e0b",
    "CCC_OAS": "#dc2626",
    "IG_OAS": "#14b8a6",
    "EM_OAS": "#a16207",
    # Macro
    "T10Y2Y": "#1e293b",
    "DXY": "#475569",
}


def _date_label(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m/%Y")


# ────────────────────────────────────────────────────────────────────────────
# Tab 1: Level (3 sub-grids)
# ────────────────────────────────────────────────────────────────────────────

def _plot_grid(df: pd.DataFrame, specs: list[tuple], rows: int, cols: int,
               height: int) -> go.Figure:
    """
    Generic helper: render N sub-plots theo specs.
    specs = [(col_name, subplot_title, ylabel), ...] (order maps to row-major).
    """
    subplot_titles = [s[1] for s in specs]
    while len(subplot_titles) < rows * cols:
        subplot_titles.append("")

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=tuple(subplot_titles),
        horizontal_spacing=0.08,
        vertical_spacing=0.18,
    )

    for i, (col, _title, ylabel) in enumerate(specs):
        r = i // cols + 1
        c = i % cols + 1
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue

        fig.add_trace(
            go.Scatter(
                x=series.index, y=series.values,
                mode="lines",
                name=col,
                line=dict(color=SERIES_COLOR.get(col, "#0f172a"), width=1.5),
                hovertemplate=f"<b>%{{x|%d/%m/%Y}}</b><br>{col}: %{{y:.2f}}<extra></extra>",
                showlegend=False,
            ),
            row=r, col=c,
        )

        mean_val = float(series.mean())
        fig.add_hline(
            y=mean_val, line_dash="dot", line_color="#64748b",
            opacity=0.6, row=r, col=c,
            annotation_text=f"mean={mean_val:.2f}",
            annotation_position="top right",
            annotation_font_size=10,
        )

        fig.update_yaxes(title_text=ylabel, row=r, col=c, gridcolor="LightGray")
        fig.update_xaxes(gridcolor="LightGray", row=r, col=c)

    fig.update_layout(
        template="plotly_white",
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        margin=dict(l=40, r=20, t=50, b=30),
    )
    return fig


def plot_level_volatility(df: pd.DataFrame) -> go.Figure:
    """
    5 panel volatility: VIX, MOVE, SKEW, OVX, VVIX.
    Layout 3x2 (slot cuối trống).
    """
    specs = [
        ("VIX",  "VIX — CBOE Equity Vol", "VIX (points)"),
        ("MOVE", "MOVE — US Bond Vol (ICE BofAML)", "MOVE (bps)"),
        ("SKEW", "SKEW — CBOE Tail Risk Premium", "SKEW (index)"),
        ("OVX",  "OVX — CBOE Oil ETF Vol", "OVX (%)"),
        ("VVIX", "VVIX — Vol-of-Vol", "VVIX (index)"),
    ]
    return _plot_grid(df, specs, rows=3, cols=2, height=720)


def plot_level_credit(df: pd.DataFrame) -> go.Figure:
    """
    4 panel credit: HY, CCC, IG, EM OAS.
    Layout 2x2.
    """
    specs = [
        ("HY_OAS",  "HY OAS — US High Yield Broad",   "HY OAS (%)"),
        ("CCC_OAS", "CCC OAS — Deep Junk",             "CCC OAS (%)"),
        ("IG_OAS",  "IG OAS — US Investment Grade",    "IG OAS (%)"),
        ("EM_OAS",  "EM OAS — Emerging Market Corp",   "EM OAS (%)"),
    ]
    return _plot_grid(df, specs, rows=2, cols=2, height=560)


def plot_level_macro(df: pd.DataFrame) -> go.Figure:
    """
    2 panel macro: 2s10s curve, DXY.
    Layout 1x2.
    """
    specs = [
        ("T10Y2Y", "2s10s Curve — 10Y minus 2Y Treasury", "Spread (%)"),
        ("DXY",    "DXY — ICE US Dollar Index",            "DXY (index)"),
    ]
    return _plot_grid(df, specs, rows=1, cols=2, height=320)


# ────────────────────────────────────────────────────────────────────────────
# Tab 2: Analytics
# ────────────────────────────────────────────────────────────────────────────

def plot_pc1_with_regime(df: pd.DataFrame) -> go.Figure:
    """
    PC1 time series với regime color-band background (STRESS/ELEVATED/CALM).
    Hai line: PC1 raw (mờ, gray) + PC1_smooth EMA(5) (đậm, dark) — regime tính trên smooth.
    """
    fig = go.Figure()

    df_valid = df.dropna(subset=["PC1", "Regime"])
    if df_valid.empty:
        fig.update_layout(title="PC1 — chưa đủ dữ liệu để hiển thị")
        return fig

    regime_arr = df_valid["Regime"].values
    dates = df_valid.index
    changes = np.where(regime_arr[:-1] != regime_arr[1:])[0]
    block_starts = [0] + (changes + 1).tolist()
    block_ends = changes.tolist() + [len(regime_arr) - 1]

    for s, e in zip(block_starts, block_ends):
        rg = regime_arr[s]
        if rg in ("N/A",):
            continue
        color = REGIME_COLOR.get(rg, "#cbd5e1")
        fig.add_vrect(
            x0=dates[s], x1=dates[e],
            fillcolor=color, opacity=0.10, line_width=0, layer="below",
        )

    # Raw PC1 — light gray, thin, mờ phía sau
    fig.add_trace(go.Scatter(
        x=df_valid.index, y=df_valid["PC1"],
        mode="lines",
        name="PC1 raw",
        line=dict(color="#94a3b8", width=1),
        opacity=0.55,
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>PC1 raw: %{y:+.2f}<extra></extra>",
        showlegend=True,
    ))

    # Smoothed PC1 — đậm, đường chính dùng regime
    if "PC1_smooth" in df_valid.columns:
        fig.add_trace(go.Scatter(
            x=df_valid.index, y=df_valid["PC1_smooth"],
            mode="lines",
            name="PC1 EMA(5)",
            line=dict(color="#0f172a", width=2.2),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>PC1 smooth: %{y:+.2f}<br>Regime: %{customdata}<extra></extra>",
            customdata=df_valid["Regime"],
            showlegend=True,
        ))

    fig.add_hline(y=0, line_color="#94a3b8", line_dash="dash")

    fig.update_layout(
        title="PC1 — Composite Financial Stress Index (6-series PCA · EMA(5) smooth · background = regime)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        height=380,
        yaxis=dict(title="PC1 (sigma)"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor="LightGray")
    fig.update_yaxes(gridcolor="LightGray")
    return fig


def plot_percentile_grid(df: pd.DataFrame) -> go.Figure:
    """
    6-panel small multiples: percentile rank 1Y của 6 PCA-core series
    (VIX, MOVE, SKEW, HY, CCC, IG). Shading vùng 80% (HIGH).
    Layout 3x2.
    """
    specs = [
        ("VIX_pct",  "VIX Percentile Rank (1Y)",  "VIX",  "VIX"),
        ("MOVE_pct", "MOVE Percentile Rank (1Y)", "MOVE", "MOVE"),
        ("SKEW_pct", "SKEW Percentile Rank (1Y)", "SKEW", "SKEW"),
        ("HY_pct",   "HY OAS Percentile Rank (1Y)",  "HY",  "HY_OAS"),
        ("CCC_pct",  "CCC OAS Percentile Rank (1Y)", "CCC", "CCC_OAS"),
        ("IG_pct",   "IG OAS Percentile Rank (1Y)",  "IG",  "IG_OAS"),
    ]

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=tuple(s[1] for s in specs),
        horizontal_spacing=0.10,
        vertical_spacing=0.15,
    )

    for i, (col, _title, label, color_key) in enumerate(specs):
        r = i // 2 + 1
        c = i % 2 + 1
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue

        fig.add_trace(
            go.Scatter(
                x=series.index, y=series.values,
                mode="lines",
                line=dict(color=SERIES_COLOR.get(color_key, "#0f172a"), width=1.5),
                showlegend=False,
                hovertemplate=f"<b>%{{x|%d/%m/%Y}}</b><br>{label}_pct: %{{y:.2f}}<extra></extra>",
            ),
            row=r, col=c,
        )

        fig.add_hrect(y0=0.80, y1=1.0,
                      fillcolor="rgba(220,38,38,0.10)", line_width=0,
                      row=r, col=c)
        fig.add_hline(y=0.80, line_dash="dash", line_color="#dc2626",
                      row=r, col=c, opacity=0.6)
        fig.add_hline(y=0.50, line_dash="dot", line_color="#94a3b8",
                      row=r, col=c, opacity=0.5)

        fig.update_yaxes(range=[0, 1.02], tickformat=".0%", row=r, col=c, gridcolor="LightGray")
        fig.update_xaxes(gridcolor="LightGray", row=r, col=c)

    fig.update_layout(
        template="plotly_white",
        height=720,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        margin=dict(l=40, r=20, t=50, b=30),
    )
    return fig


def plot_pc_scatter(df: pd.DataFrame, n_recent: int = 252) -> go.Figure:
    """
    Scatter PC1 vs PC2, last n_recent ngày, gradient color theo recency.
    """
    df_valid = df.dropna(subset=["PC1", "PC2"]).tail(n_recent)
    fig = go.Figure()

    if df_valid.empty:
        fig.update_layout(title="PC2 vs PC1 — chưa đủ dữ liệu")
        return fig

    fig.add_trace(go.Scatter(
        x=df_valid["PC1"], y=df_valid["PC2"],
        mode="markers",
        marker=dict(
            size=7,
            color=list(range(len(df_valid))),
            colorscale="Plasma",
            showscale=True,
            colorbar=dict(title="Recency", tickvals=[0, len(df_valid) - 1],
                          ticktext=["Cũ", "Mới"]),
            line=dict(width=0.5, color="#0f172a"),
        ),
        text=[_date_label(d) for d in df_valid.index],
        hovertemplate="<b>%{text}</b><br>PC1: %{x:+.2f}<br>PC2: %{y:+.2f}<extra></extra>",
    ))

    if not df_valid.empty:
        last = df_valid.iloc[-1]
        fig.add_trace(go.Scatter(
            x=[last["PC1"]], y=[last["PC2"]],
            mode="markers+text",
            marker=dict(size=14, color="#dc2626", symbol="star",
                        line=dict(width=1.5, color="black")),
            text=["Latest"],
            textposition="top right",
            showlegend=False,
            hoverinfo="skip",
        ))

    fig.add_hline(y=0, line_color="#94a3b8", line_dash="dot")
    fig.add_vline(x=0, line_color="#94a3b8", line_dash="dot")

    fig.update_layout(
        title=f"PC2 vs PC1 — last {len(df_valid)} sessions (color = recency)",
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        height=440,
        xaxis=dict(title="PC1 (stress)", gridcolor="LightGray"),
        yaxis=dict(title="PC2 (divergence)", gridcolor="LightGray"),
        showlegend=False,
    )
    return fig


def plot_credit_quality_spread(df: pd.DataFrame) -> go.Figure:
    """
    Credit Quality Spread (CCC − HY) line + percentile shading.
    """
    df_valid = df.dropna(subset=["Credit_Quality_Spread"])
    fig = go.Figure()

    if df_valid.empty:
        fig.update_layout(title="Credit Quality Spread — chưa đủ dữ liệu")
        return fig

    fig.add_trace(go.Scatter(
        x=df_valid.index, y=df_valid["Credit_Quality_Spread"],
        mode="lines",
        name="CCC − HY",
        line=dict(color="#be123c", width=2),
        fill="tozeroy",
        fillcolor="rgba(190, 18, 60, 0.08)",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>CCC−HY: %{y:.2f}%<extra></extra>",
    ))

    if "CQS_pct" in df_valid.columns and df_valid["CQS_pct"].notna().any():
        latest_pct = df_valid["CQS_pct"].dropna().iloc[-1]
        fig.add_annotation(
            x=df_valid.index[-1], y=df_valid["Credit_Quality_Spread"].iloc[-1],
            text=f"PR 1Y: {latest_pct*100:.0f}%",
            showarrow=True, arrowhead=2, arrowcolor="#be123c",
            font=dict(color="#be123c", size=11),
            bgcolor="white", bordercolor="#be123c", borderwidth=1,
        )

    mean_val = float(df_valid["Credit_Quality_Spread"].mean())
    fig.add_hline(y=mean_val, line_dash="dot", line_color="#64748b",
                  annotation_text=f"mean={mean_val:.2f}%",
                  annotation_position="bottom right")

    fig.update_layout(
        title="Credit Quality Spread — CCC OAS minus HY OAS (default-cycle indicator)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        showlegend=False,
        height=360,
        yaxis=dict(title="Spread (%)"),
    )
    fig.update_xaxes(gridcolor="LightGray")
    fig.update_yaxes(gridcolor="LightGray")
    return fig


def plot_margin_debt_m2_overlay(df: pd.DataFrame) -> go.Figure:
    """
    Monthly US margin debt / M2 overlay. This chart is not part of GFCM PCA.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df is None or df.empty:
        fig.update_layout(title="US Margin Debt / M2 — chưa có dữ liệu")
        return fig

    work = df.copy()
    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        work = work.set_index("date")
    work = work.sort_index()

    if "margin_debt_pct_m2" not in work.columns:
        fig.update_layout(title="US Margin Debt / M2 — thiếu cột margin_debt_pct_m2")
        return fig

    valid = work.dropna(subset=["margin_debt_pct_m2"])
    if valid.empty:
        fig.update_layout(title="US Margin Debt / M2 — chưa đủ dữ liệu")
        return fig

    fig.add_trace(
        go.Scatter(
            x=valid.index,
            y=valid["margin_debt_pct_m2"],
            mode="lines",
            name="Margin debt / M2",
            line=dict(color="#2563eb", width=2.1),
            hovertemplate="<b>%{x|%m/%Y}</b><br>Margin/M2: %{y:.2f}%<extra></extra>",
        ),
        secondary_y=False,
    )

    if "margin_debt_pct_m2_percentile_10y" in valid.columns:
        pct = valid["margin_debt_pct_m2_percentile_10y"].dropna()
        if not pct.empty:
            fig.add_trace(
                go.Scatter(
                    x=pct.index,
                    y=pct.values,
                    mode="lines",
                    name="10Y percentile",
                    line=dict(color="#f59e0b", width=1.7, dash="dot"),
                    hovertemplate="<b>%{x|%m/%Y}</b><br>10Y percentile: %{y:.0f}<extra></extra>",
                ),
                secondary_y=True,
            )
            fig.add_hline(
                y=85,
                line_dash="dash",
                line_color="#f59e0b",
                opacity=0.55,
                secondary_y=True,
                annotation_text="85th pct",
                annotation_position="top right",
            )

    mean_val = float(valid["margin_debt_pct_m2"].mean())
    fig.add_hline(
        y=mean_val,
        line_dash="dot",
        line_color="#64748b",
        opacity=0.65,
        secondary_y=False,
        annotation_text=f"mean={mean_val:.2f}%",
        annotation_position="bottom right",
    )

    latest = valid.iloc[-1]
    latest_date = valid.index[-1]
    regime = latest.get("signal_regime", "N/A")
    fig.add_annotation(
        x=latest_date,
        y=float(latest["margin_debt_pct_m2"]),
        text=f"{regime}",
        showarrow=True,
        arrowhead=2,
        arrowcolor="#2563eb",
        font=dict(color="#1d4ed8", size=11),
        bgcolor="white",
        bordercolor="#2563eb",
        borderwidth=1,
    )

    fig.update_layout(
        title="US Margin Debt / M2 — Speculative Leverage Overlay (monthly · not in PCA)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Margin debt / M2 (%)", gridcolor="LightGray", secondary_y=False)
    fig.update_yaxes(title_text="10Y percentile", range=[0, 100], gridcolor="LightGray", secondary_y=True)
    fig.update_xaxes(gridcolor="LightGray")
    return fig
