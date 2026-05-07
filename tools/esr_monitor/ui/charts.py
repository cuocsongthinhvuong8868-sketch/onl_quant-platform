import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_esr_chart(df):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df.index, y=df["SSI_Index"], mode="lines", name="SSI", line=dict(color="#b91c1c", width=2.5)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df.index, y=df["INDEX_Close"], mode="lines", name="VN Index", line=dict(color="#2563eb", width=2)), secondary_y=True)
    ma_cols = [c for c in df.columns if c.startswith("MA")]
    if ma_cols:
        fig.add_trace(go.Scatter(x=df.index, y=df[ma_cols[0]], mode="lines", name=ma_cols[0], line=dict(color="#f59e0b", width=1.5)), secondary_y=True)

    fig.update_layout(hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
    fig.update_yaxes(title_text="SSI", secondary_y=False)
    fig.update_yaxes(title_text="Index", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)
