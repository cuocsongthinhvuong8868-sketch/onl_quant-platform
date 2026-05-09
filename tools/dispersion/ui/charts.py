import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import numpy as np


def render_main_chart(df_metrics, recent_window_2d: int):
    st.subheader("1) Time Series: DPI & Correlation")
    fig1 = make_subplots(specs=[[{"secondary_y": True}]])
    fig1.add_trace(go.Scatter(x=df_metrics.index, y=df_metrics["DPI"], mode="lines", name="DPI", line=dict(color="#cc0066", width=2)), secondary_y=False)
    fig1.add_trace(go.Scatter(x=df_metrics.index, y=df_metrics["Ledoit_Correlation"], mode="lines", name="Corr", line=dict(color="#0066cc", width=1.5)), secondary_y=True)
    
    fig1.add_hline(y=50, line_dash='dot', line_color='gray', annotation_text="50% (neutral)", secondary_y=False)

    fig1.update_layout(hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
    fig1.update_yaxes(title_text="DPI (%)", range=[0, 100], secondary_y=False)
    fig1.update_yaxes(title_text="Correlation", secondary_y=True)
    st.plotly_chart(fig1, use_container_width=True)

    st.subheader(f"2) 2D Regime Map (Pure Observation)")
    map_df = df_metrics[['DPI', 'Ledoit_Correlation']].dropna()
    if len(map_df) > 0:
        all_x = map_df['Ledoit_Correlation'].values
        all_y = map_df['DPI'].values
        color_vals = np.linspace(0, 1, len(map_df))

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=all_x, y=all_y,
            mode='markers',
            marker=dict(
                size=5,
                color=color_vals,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(
                    title="Recency",
                    tickmode='array',
                    tickvals=[0, 1],
                    ticktext=[f'{map_df.index[0].date()}', f'{map_df.index[-1].date()}']
                ),
                opacity=0.6
            ),
            text=[f"{d.date()}<br>DPI={y:.1f}%<br>Corr={x:.3f}" for d, x, y in zip(map_df.index, all_x, all_y)],
            hoverinfo='text',
            name='Historical days'
        ))

        recent_df = map_df.iloc[-recent_window_2d:] if len(map_df) >= recent_window_2d else map_df
        fig2.add_trace(go.Scatter(
            x=recent_df['Ledoit_Correlation'].values,
            y=recent_df['DPI'].values,
            mode='markers+lines',
            marker=dict(size=10, color='red', line=dict(color='black', width=1)),
            line=dict(color='rgba(255,0,0,0.4)', width=1),
            text=[f"{d.date()}<br>DPI={y:.1f}%<br>Corr={x:.3f}" for d, x, y in zip(recent_df.index, recent_df['Ledoit_Correlation'].values, recent_df['DPI'].values)],
            hoverinfo='text',
            name=f'Last {recent_window_2d} days'
        ))
        
        fig2.update_layout(
            xaxis_title="Avg Pairwise Correlation (Ledoit-Wolf)",
            yaxis_title="DPI (%)",
            hovermode="closest",
            height=600,
            template="plotly_white"
        )
        st.plotly_chart(fig2, use_container_width=True)

