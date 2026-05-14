import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

RANGESELECTOR_DICT = dict(
    buttons=list([
        dict(count=6, label="6M", step="month", stepmode="backward"),
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(count=3, label="3Y", step="year", stepmode="backward"),
        dict(count=5, label="5Y", step="year", stepmode="backward"),
        dict(step="all", label="All"),
    ]), bgcolor="#e5e7eb", activecolor="#9ca3af",
)

SIGNAL_COLOR = {
    "ADD": "#16a34a",
    "CUT": "#dc2626",
    "HOLD": "#f59e0b",
}


def plot_net_liquidity(df: pd.DataFrame) -> go.Figure:
    """
    Biểu đồ Net Liquidity line với chấm tô màu theo Signal (ADD/CUT/HOLD).
    """
    fig = go.Figure()

    colors = [SIGNAL_COLOR.get(s, "#888888") for s in df["Signal"]]

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Net_Liquidity"],
        mode="lines",
        name="Net Liquidity",
        line=dict(color="#0284c7", width=2),
        fill="tozeroy",
        fillcolor="rgba(2, 132, 199, 0.08)",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Net Liq: %{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Net_Liquidity"],
        mode="markers",
        name="Signal",
        marker=dict(
            size=7,
            color=colors,
            line=dict(width=1, color="#0f172a"),
        ),
        text=df["Signal"],
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Signal: %{text}<br>Net Liq: %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title="Fed Net Liquidity Level (Chấm theo Signal: 🟢 ADD · 🔴 CUT · 🟡 HOLD)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        showlegend=False,
        height=420,
        yaxis=dict(title="Net Liquidity (Million $)", tickformat=",.0f"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="LightGray", rangeselector=RANGESELECTOR_DICT)
    fig.update_yaxes(showgrid=True, gridcolor="LightGray")
    return fig


def plot_momentum(df: pd.DataFrame) -> go.Figure:
    """
    Biểu đồ Momentum: bar Impulse + line EMA.
    """
    fig = go.Figure()

    bar_colors = ["#4ade80" if v >= 0 else "#f87171" for v in df["Impulse"].fillna(0)]

    fig.add_trace(go.Bar(
        x=df.index, y=df["Impulse"],
        name="Weekly Impulse",
        marker_color=bar_colors,
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Impulse: %{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Impulse_EMA"],
        mode="lines",
        name="EMA(4)",
        line=dict(color="#f59e0b", width=2.5),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>EMA: %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title="Momentum Engine — Weekly Impulse vs EMA(4)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        height=360,
        yaxis=dict(title="Δ Net Liquidity (Million $)", tickformat=",.0f"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="LightGray", rangeselector=RANGESELECTOR_DICT)
    fig.update_yaxes(showgrid=True, gridcolor="LightGray", zeroline=True, zerolinecolor="#9ca3af")
    return fig


def plot_zscore(df: pd.DataFrame) -> go.Figure:
    """
    Z-Score chart với vùng signal ADD/CUT.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Z_Score"],
        mode="lines",
        name="Z-Score (Impulse, 52W)",
        line=dict(color="#7c3aed", width=2),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Z: %{y:.2f}<extra></extra>",
    ))

    fig.add_hrect(y0=1, y1=df["Z_Score"].max() if df["Z_Score"].max() > 1 else 3,
                  fillcolor="rgba(34,197,94,0.10)", line_width=0)
    fig.add_hrect(y0=df["Z_Score"].min() if df["Z_Score"].min() < -1 else -3, y1=-1,
                  fillcolor="rgba(239,68,68,0.10)", line_width=0)
    fig.add_hline(y=1, line_dash="dash", line_color="#16a34a", annotation_text="ADD threshold (+1)")
    fig.add_hline(y=-1, line_dash="dash", line_color="#dc2626", annotation_text="CUT threshold (-1)")
    fig.add_hline(y=0, line_color="#94a3b8")

    fig.update_layout(
        title="Z-Score Impulse (52W Rolling)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="black"),
        showlegend=False,
        height=300,
        yaxis=dict(title="Z-Score"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="LightGray", rangeselector=RANGESELECTOR_DICT)
    fig.update_yaxes(showgrid=True, gridcolor="LightGray")
    return fig
