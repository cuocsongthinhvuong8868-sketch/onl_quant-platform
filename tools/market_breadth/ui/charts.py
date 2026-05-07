import plotly.graph_objects as go
import streamlit as st


COLORS = {
    "> MA20": "#1f77b4",
    "> MA60": "#ff7f0e",
    "> MA125": "#2ca02c",
    "> MA252": "#d62728",
}


def render_breadth_chart(df_plot, start_date, end_date):
    fig = go.Figure()
    for col in df_plot.columns:
        fig.add_trace(
            go.Scatter(
                x=df_plot.index,
                y=df_plot[col],
                mode="lines",
                name=col,
                line=dict(width=2, color=COLORS[col]),
            )
        )

    fig.update_layout(
        title=f"Số lượng cổ phiếu trên các đường MA ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
        xaxis_title="Thời gian",
        yaxis_title="Số lượng cổ phiếu",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)
