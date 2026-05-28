import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

RANGESELECTOR_DICT = dict(
    buttons=list([
        dict(count=3, label="3M", step="month", stepmode="backward"),
        dict(count=6, label="6M", step="month", stepmode="backward"),
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(count=2, label="2Y", step="year", stepmode="backward"),
        dict(step="all", label="All"),
    ]), bgcolor="#f3f4f6", activecolor="#cbd5e1",
)

REGIME_COLORS = {
    "TIGHT": "#ef4444",      # Red
    "ELEVATED": "#f97316",   # Orange
    "NORMAL": "#3b82f6",     # Blue
    "EASY": "#10b981",       # Green
}

SIGNAL_COLORS = {
    "STRESS": "#ef4444",
    "WARNING": "#f59e0b",
    "ACCOMMODATIVE": "#10b981",
    "NEUTRAL": "#64748b"
}

def plot_vnibor_rates(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ liên tục 3 loại lãi suất: Overnight_ON, 1_Week, 2_Weeks."""
    fig = go.Figure()

    # 1. Overnight ON
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Overnight_ON"],
        mode="lines",
        name="Lãi suất Qua đêm (ON)",
        line=dict(color="#2563eb", width=2.5),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Qua đêm (ON): <b>%{y:.2f}%</b><extra></extra>",
    ))

    # 2. 1-Week
    fig.add_trace(go.Scatter(
        x=df.index, y=df["1_Week"],
        mode="lines",
        name="Lãi suất 1 Tuần",
        line=dict(color="#10b981", width=1.5, dash="dash"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Kỳ hạn 1 Tuần: <b>%{y:.2f}%</b><extra></extra>",
    ))

    # 3. 2-Weeks
    fig.add_trace(go.Scatter(
        x=df.index, y=df["2_Weeks"],
        mode="lines",
        name="Lãi suất 2 Tuần",
        line=dict(color="#d97706", width=1.5, dash="dot"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Kỳ hạn 2 Tuần: <b>%{y:.2f}%</b><extra></extra>",
    ))

    fig.update_layout(
        title="Lãi suất Liên ngân hàng Việt Nam (VNIBOR) theo Kỳ hạn",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="#1f2937"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        height=420,
        yaxis=dict(title="Lãi suất (%)", tickformat=".2f"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f3f4f6", rangeselector=RANGESELECTOR_DICT)
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
    return fig

def plot_vnibor_spreads(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ chênh lệch kỳ hạn (Spreads) 1W-ON và 2W-ON."""
    fig = go.Figure()

    # 1. Spread 1W - ON
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Spread_1W_ON"],
        mode="lines",
        name="Spread 1W - ON",
        line=dict(color="#06b6d4", width=2),
        fill="tozeroy",
        fillcolor="rgba(6, 182, 212, 0.05)",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Spread 1W - ON: <b>%{y:+.2f}%</b><extra></extra>",
    ))

    # 2. Spread 2W - ON
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Spread_2W_ON"],
        mode="lines",
        name="Spread 2W - ON",
        line=dict(color="#8b5cf6", width=1.5, dash="dash"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Spread 2W - ON: <b>%{y:+.2f}%</b><extra></extra>",
    ))

    # Thêm đường tham chiếu y = 0
    fig.add_trace(go.Scatter(
        x=[df.index.min(), df.index.max()], y=[0, 0],
        mode="lines",
        name="Đường tham chiếu 0%",
        line=dict(color="#ef4444", width=1.5, dash="dash"),
        showlegend=False,
        hoverinfo="skip"
    ))

    fig.update_layout(
        title="Độ dốc Đường cong Lãi suất liên ngân hàng (Spreads vs ON)",
        template="plotly_white",
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="#1f2937"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        height=380,
        yaxis=dict(title="Chênh lệch (%)", tickformat="+.2f"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f3f4f6")
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
    return fig

def plot_vnibor_regime(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ lãi suất qua đêm ON phân tích theo trạng thái thanh khoản (Regime)."""
    fig = go.Figure()

    # Thêm đường nền
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Overnight_ON"],
        mode="lines",
        name="Lãi suất ON (Đường dẫn)",
        line=dict(color="#e2e8f0", width=1.0),
        showlegend=False,
        hoverinfo="skip"
    ))

    # Thêm đường mượt MA(5) của ON làm tham chiếu chính cho phân loại
    if "ON_5D_Mean" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ON_5D_Mean"],
            mode="lines",
            name="MA(5) Qua đêm (Đường mượt)",
            line=dict(color="#475569", width=2, dash="dash"),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>MA(5) Qua đêm: <b>%{y:.2f}%</b><extra></extra>",
        ))

    # Vẽ các scatter point tương ứng với từng Regime
    for regime, color in REGIME_COLORS.items():
        sub_df = df[df["Regime"] == regime]
        if not sub_df.empty:
            regime_vn = {"TIGHT": "Thắt chặt (TIGHT)", "ELEVATED": "Cận thắt chặt (ELEVATED)", 
                         "NORMAL": "Bình thường (NORMAL)", "EASY": "Dồi dào (EASY)"}.get(regime, regime)
            
            fig.add_trace(go.Scatter(
                x=sub_df.index, y=sub_df["Overnight_ON"],
                mode="markers",
                name=regime_vn,
                marker=dict(size=6, color=color),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Lãi suất ON: <b>%{y:.2f}%</b><br>Trạng thái: <b>" + regime_vn + "</b><extra></extra>",
            ))

    fig.update_layout(
        title="Trạng thái Thanh khoản Liên ngân hàng (Regime phân loại theo Percentile 1Y)",
        template="plotly_white",
        hovermode="closest",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="#1f2937"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        height=400,
        yaxis=dict(title="Lãi suất ON (%)", tickformat=".2f"),
        xaxis=dict(title=""),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f3f4f6")
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
    return fig
