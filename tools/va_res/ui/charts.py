import plotly.graph_objects as go
import numpy as np
import pandas as pd

RANGESELECTOR_DICT = dict(
    buttons=list([
        dict(count=30, label="30 Ngày", step="day", stepmode="backward"),
        dict(count=60, label="60 Ngày", step="day", stepmode="backward"),
        dict(count=1, label="1 Năm", step="year", stepmode="backward"),
        dict(count=3, label="3 Năm", step="year", stepmode="backward"),
        dict(step="all", label="Tất cả")
    ]), bgcolor="#e5e7eb", activecolor="#9ca3af"
)

def plot_individual_risk(p_std20, p_var, p_es, ticker):
    fig_ply = go.Figure()
    fig_ply.add_trace(go.Scatter(x=p_std20.index, y=p_std20, mode='lines', name='-20d Stdev', line=dict(color='gray', width=1.5, dash='dot')))
    fig_ply.add_trace(go.Scatter(x=p_var.index, y=p_var, mode='lines', name='CF VaR 95%', line=dict(color='red', dash='dash')))
    fig_ply.add_trace(go.Scatter(x=p_es.index, y=p_es, mode='lines', name='Robust ES', line=dict(color='purple'), fill='tonexty', fillcolor='rgba(128, 0, 128, 0.15)'))
    fig_ply.update_layout(title=f'Băng thông Rủi ro (Risk Band) {ticker}', template='plotly_white', hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white', font=dict(color='black'))
    fig_ply.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray', rangeselector=RANGESELECTOR_DICT)
    fig_ply.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    return fig_ply

def plot_systemic_risk(stress_index, threshold=0.40):
    fig_ply = go.Figure()
    fig_ply.add_trace(go.Scatter(x=stress_index.index, y=stress_index, mode='lines', name='% Cổ phiếu thủng VaR', line=dict(color='teal', width=2)))
    fig_ply.add_hline(y=threshold * 100, line_dash="dash", line_color="red", annotation_text=f"Ngưỡng Báo động Đỏ ({threshold*100}%)")
    fig_ply.update_layout(template='plotly_white', yaxis=dict(range=[0, 105]), hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white', font=dict(color='black'))
    fig_ply.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray', rangeselector=RANGESELECTOR_DICT)
    fig_ply.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    return fig_ply

def plot_complacency_index(complacency_index, threshold=0.80):
    fig_ply = go.Figure()
    fig_ply.add_trace(go.Scatter(x=complacency_index.index, y=complacency_index, mode='lines', name='% Cổ phiếu Mispriced', line=dict(color='darkorange', width=2)))
    fig_ply.add_hline(y=threshold * 100, line_dash="dash", line_color="red", annotation_text=f"Ngưỡng Nguy hiểm ({threshold*100}%)")
    fig_ply.update_layout(template='plotly_white', yaxis=dict(range=[0, 105]), hovermode='x unified', plot_bgcolor='white', paper_bgcolor='white', font=dict(color='black'))
    fig_ply.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray', rangeselector=RANGESELECTOR_DICT)
    fig_ply.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    return fig_ply
