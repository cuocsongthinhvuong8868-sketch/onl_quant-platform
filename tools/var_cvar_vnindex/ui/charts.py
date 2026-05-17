import plotly.graph_objects as go
from plotly.subplots import make_subplots
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


def plot_var_cvar(df_plot: pd.DataFrame):
    """
    Vẽ biểu đồ VaR-CVaR VNINDEX (classic) với 4 traces:
      - Stdev 30 (gray)
      - Parametric VaR 95% (red dash)
      - Historical VaR 95% (blue dash-dot)
      - Expected Shortfall (purple solid + fill)
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot['stdev_30'] * 100,
        mode='lines', name='σ 30 ngày',
        line=dict(color='gray', width=1.5, dash='dot')
    ))

    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot['parametric_var'] * 100,
        mode='lines', name='Parametric VaR 95%',
        line=dict(color='red', width=1.5, dash='dash')
    ))

    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot['historical_var'] * 100,
        mode='lines', name='Historical VaR 95%',
        line=dict(color='blue', width=1.5, dash='dashdot')
    ))

    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot['expected_shortfall'] * 100,
        mode='lines', name='Expected Shortfall 95%',
        line=dict(color='purple', width=2),
        fill='tonexty', fillcolor='rgba(128, 0, 128, 0.12)'
    ))

    fig.update_layout(
        title='VNINDEX — VaR & CVaR (ES) 95%',
        template='plotly_white',
        hovermode='x unified',
        plot_bgcolor='white',
        paper_bgcolor='white',
        font=dict(color='black'),
        legend=dict(orientation='h', yanchor='bottom', y=-0.25, xanchor='center', x=0.5),
        yaxis=dict(title='Return / VaR / ES (%)', tickformat='.2f'),
        xaxis=dict(title=''),
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray', rangeselector=RANGESELECTOR_DICT)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')

    return fig


def plot_evt_tail_risk(df_plot: pd.DataFrame):
    """
    Biểu đồ EVT 2 subplot:
      Subplot 1: VaR/ES tại 95%, 99%, 99.5% (POT-GPD extrapolated).
                 So sánh trực tiếp với Historical VaR 95% và Parametric VaR 95%
                 để thấy Gaussian underestimate tail risk như thế nào.
      Subplot 2: ξ (GPD shape) + Hill index theo thời gian.
                 ξ > 0.15 = heavy tail; > 0.3 = fat tail thật sự.
                 Spike trong stress regime → cảnh báo trước drawdown.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.08,
        subplot_titles=(
            "EVT VaR/ES tại quantile cực đoan (POT-GPD extrapolation)",
            "ξ (GPD shape) + Hill index — chỉ số đuôi nặng (heavy tail signal)",
        ),
    )

    # ── Subplot 1: VaR/ES ──
    if 'parametric_var' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['parametric_var'] * 100,
            mode='lines', name='Gaussian VaR 95% (so sánh)',
            line=dict(color='red', width=1, dash='dot'),
            legendgroup='gauss',
        ), row=1, col=1)

    if 'historical_var' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['historical_var'] * 100,
            mode='lines', name='Historical VaR 95% (so sánh)',
            line=dict(color='blue', width=1, dash='dot'),
            legendgroup='hist',
        ), row=1, col=1)

    # EVT VaR — colors: lighter→darker theo độ extreme
    if 'evt_var_95' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['evt_var_95'] * 100,
            mode='lines', name='EVT VaR 95%',
            line=dict(color='#f59e0b', width=1.5),
        ), row=1, col=1)
    if 'evt_var_99' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['evt_var_99'] * 100,
            mode='lines', name='EVT VaR 99%',
            line=dict(color='#dc2626', width=2),
        ), row=1, col=1)
    if 'evt_var_995' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['evt_var_995'] * 100,
            mode='lines', name='EVT VaR 99.5%',
            line=dict(color='#7c2d12', width=2, dash='dash'),
        ), row=1, col=1)

    # EVT ES 99% với fill
    if 'evt_es_99' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['evt_es_99'] * 100,
            mode='lines', name='EVT ES 99% (CVaR)',
            line=dict(color='#7c3aed', width=2.5),
            fill='tonexty', fillcolor='rgba(124,58,237,0.10)',
        ), row=1, col=1)

    # ── Subplot 2: ξ + Hill ──
    if 'evt_xi' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['evt_xi'],
            mode='lines', name='ξ (GPD shape)',
            line=dict(color='#059669', width=2),
        ), row=2, col=1)
    if 'hill_index' in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['hill_index'],
            mode='lines', name='Hill index',
            line=dict(color='#0891b2', width=1.5, dash='dash'),
        ), row=2, col=1)

    # Reference lines cho ξ
    fig.add_hline(y=0, line_dash="solid", line_color="gray", line_width=1,
                  row=2, col=1, opacity=0.5)
    fig.add_hline(y=0.15, line_dash="dot", line_color="orange", line_width=1,
                  row=2, col=1, opacity=0.6,
                  annotation_text="Heavy tail threshold (0.15)",
                  annotation_position="right",
                  annotation_font_size=10)
    fig.add_hline(y=0.30, line_dash="dot", line_color="red", line_width=1,
                  row=2, col=1, opacity=0.6,
                  annotation_text="Fat tail (0.30)",
                  annotation_position="right",
                  annotation_font_size=10)

    fig.update_layout(
        height=650,
        template='plotly_white',
        hovermode='x unified',
        plot_bgcolor='white',
        paper_bgcolor='white',
        font=dict(color='black'),
        legend=dict(orientation='h', yanchor='bottom', y=-0.18, xanchor='center', x=0.5),
        margin=dict(t=60, b=80),
    )
    fig.update_yaxes(title_text="VaR / ES (%)", tickformat='.2f', row=1, col=1)
    fig.update_yaxes(title_text="Tail index", row=2, col=1)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray',
                     rangeselector=RANGESELECTOR_DICT, row=2, col=1)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray', row=1, col=1)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')

    return fig
