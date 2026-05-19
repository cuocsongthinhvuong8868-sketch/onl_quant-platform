"""
charts.py — Plotly charts cho Pairs Trading dashboard.

6 chart functions:
- render_spread_chart        : 2-row spread + z-score with ±entry/±stop bands
- render_cluster_heatmap     : NxN EG p-value heatmap (red <0.05 = cointegrated)
- render_backtest_equity     : equity curve + drawdown
- render_residual_diagnostics: residual time-series + ACF + ADF stat
- render_pair_rho_chart      : DCC/EWMA time-series ρ_t với min threshold band
- render_correlation_heatmap : NxN current correlation matrix (EWMA last-date)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_spread_chart(
    spread: pd.Series,
    z: pd.Series,
    signals: pd.DataFrame,
    z_entry: float = 2.0,
    z_stop: float = 3.0,
    title: str = "Spread + Z-score",
) -> go.Figure:
    """2-row plot: spread top, z-score bottom với ±entry / ±stop bands + trade markers."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=("Log Spread = log(P1) - β·log(P2)", "Z-score 60d"),
        row_heights=[0.45, 0.55],
    )

    # Row 1: spread
    fig.add_trace(
        go.Scatter(x=spread.index, y=spread.values, mode="lines",
                   name="Spread", line=dict(color="#2980B9", width=1.2)),
        row=1, col=1,
    )

    # Row 2: z-score + bands
    fig.add_trace(
        go.Scatter(x=z.index, y=z.values, mode="lines",
                   name="Z-score", line=dict(color="#16A085", width=1.2)),
        row=2, col=1,
    )
    for level, color in [
        (z_entry, "rgba(255,165,0,0.5)"),
        (-z_entry, "rgba(255,165,0,0.5)"),
        (z_stop, "rgba(220,50,50,0.6)"),
        (-z_stop, "rgba(220,50,50,0.6)"),
        (0.0, "rgba(120,120,120,0.4)"),
    ]:
        fig.add_hline(y=level, line=dict(color=color, dash="dash"), row=2, col=1)

    # Trade markers (entry points)
    new_entry = signals[
        (signals["position"] != 0)
        & (signals["position"].shift(1).fillna(0) == 0)
    ]
    if not new_entry.empty:
        for _, row in new_entry.iterrows():
            color = "#27AE60" if row["position"] > 0 else "#C0392B"
            fig.add_vline(
                x=row.name, line=dict(color=color, width=1, dash="dot"),
                opacity=0.5, row=2, col=1,
            )

    fig.update_layout(
        title=title,
        height=600,
        showlegend=True,
        margin=dict(l=10, r=10, t=70, b=10),
        hovermode="x unified",
    )
    return fig


def render_cluster_heatmap(pvalue_matrix: pd.DataFrame, threshold: float = 0.05) -> go.Figure:
    """NxN EG p-value heatmap. Red = cointegrated, gray = not."""
    z = pvalue_matrix.values.astype(float)
    text = np.where(
        np.isnan(z), "",
        np.array([[f"{v:.3f}" if v < 1.0 else "—" for v in row] for row in z]),
    )
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=list(pvalue_matrix.columns),
            y=list(pvalue_matrix.index),
            colorscale=[
                [0.0, "rgb(180, 30, 30)"],       # ≤0.01 strongly cointegrated
                [threshold, "rgb(255, 200, 80)"], # ≤0.05
                [threshold * 2, "rgb(220, 220, 220)"],  # weak
                [1.0, "rgb(200, 200, 200)"],     # no relation
            ],
            zmin=0, zmax=1,
            text=text,
            texttemplate="%{text}",
            colorbar=dict(title="p-value"),
        )
    )
    fig.update_layout(
        title=f"Pairwise Engle-Granger p-value (cointegrated if < {threshold})",
        height=450,
        margin=dict(l=10, r=10, t=70, b=10),
    )
    return fig


def render_backtest_equity(equity_curve: pd.DataFrame, title: str = "Backtest Equity") -> go.Figure:
    """2-row: equity top, drawdown bottom."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=("Equity (1 = initial)", "Drawdown"),
        row_heights=[0.65, 0.35],
    )
    fig.add_trace(
        go.Scatter(x=equity_curve.index, y=equity_curve["equity"], mode="lines",
                   name="Equity", line=dict(color="#27AE60", width=1.5)),
        row=1, col=1,
    )
    fig.add_hline(y=1.0, line=dict(color="rgba(120,120,120,0.5)", dash="dash"), row=1, col=1)

    fig.add_trace(
        go.Scatter(x=equity_curve.index, y=equity_curve["drawdown"], mode="lines",
                   name="DD", fill="tozeroy", line=dict(color="#C0392B", width=1.2)),
        row=2, col=1,
    )

    fig.update_layout(
        title=title,
        height=500,
        showlegend=False,
        margin=dict(l=10, r=10, t=70, b=10),
        hovermode="x unified",
    )
    return fig


def render_residual_diagnostics(resid: pd.Series, adf_stat: float, p_value: float) -> go.Figure:
    """Residual time-series + ADF readout."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=False, vertical_spacing=0.12,
        subplot_titles=("Residual (EG spread)", "ACF (lag 1-20)"),
        row_heights=[0.6, 0.4],
    )

    fig.add_trace(
        go.Scatter(x=resid.index, y=resid.values, mode="lines",
                   name="Residual", line=dict(color="#8E44AD", width=1.2)),
        row=1, col=1,
    )
    fig.add_hline(y=0, line=dict(color="rgba(120,120,120,0.6)", dash="dash"), row=1, col=1)

    # ACF
    s = resid.dropna().values
    n_lag = min(20, len(s) // 4)
    acf = []
    if len(s) > n_lag:
        mean = np.mean(s)
        var = np.var(s)
        for lag in range(1, n_lag + 1):
            cov = np.mean((s[lag:] - mean) * (s[:-lag] - mean))
            acf.append(cov / var if var > 0 else 0.0)
    fig.add_trace(
        go.Bar(x=list(range(1, len(acf) + 1)), y=acf, name="ACF",
               marker=dict(color="#3498DB")),
        row=2, col=1,
    )
    # 95% CI ≈ ±1.96/√N
    if len(s) > 0:
        ci = 1.96 / np.sqrt(len(s))
        for level in (ci, -ci):
            fig.add_hline(y=level, line=dict(color="rgba(220,50,50,0.4)", dash="dash"), row=2, col=1)

    fig.update_layout(
        title=f"Residual diagnostics — ADF stat={adf_stat:.3f}, p-value={p_value:.4f}",
        height=500,
        showlegend=False,
        margin=dict(l=10, r=10, t=70, b=10),
    )
    return fig


def render_pair_rho_chart(
    rho_series: pd.Series,
    min_rho: float = 0.5,
    method: str = "ewma",
    title: str | None = None,
) -> go.Figure:
    """Time-series ρ_t cho 1 pair với min threshold band."""
    if title is None:
        title = f"Dynamic correlation ρ_t ({method.upper()})"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=rho_series.index, y=rho_series.values, mode="lines",
            name="ρ_t", line=dict(color="#8E44AD", width=1.3),
        )
    )
    fig.add_hline(
        y=min_rho, line=dict(color="rgba(220,50,50,0.7)", dash="dash"),
        annotation_text=f"min ρ = {min_rho:.2f}",
        annotation_position="top right",
    )
    fig.add_hline(y=0, line=dict(color="rgba(120,120,120,0.4)", dash="dot"))
    fig.update_layout(
        title=title,
        height=320,
        showlegend=False,
        margin=dict(l=10, r=10, t=60, b=10),
        yaxis=dict(range=[-1.05, 1.05], title="ρ"),
    )
    return fig


def render_correlation_heatmap(
    corr_matrix: pd.DataFrame,
    title: str = "Current correlation ρ (EWMA last-date)",
) -> go.Figure:
    """NxN correlation heatmap. Green = high positive, red = low/negative."""
    z = corr_matrix.values.astype(float)
    text = np.array([[f"{v:.2f}" for v in row] for row in z])
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=list(corr_matrix.columns),
            y=list(corr_matrix.index),
            colorscale="RdYlGn",
            zmin=-1, zmax=1,
            text=text,
            texttemplate="%{text}",
            colorbar=dict(title="ρ"),
        )
    )
    fig.update_layout(
        title=title,
        height=450,
        margin=dict(l=10, r=10, t=70, b=10),
    )
    return fig
