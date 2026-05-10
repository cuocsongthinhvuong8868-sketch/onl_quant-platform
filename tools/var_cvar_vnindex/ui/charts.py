import plotly.graph_objects as go
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
    Vẽ biểu đồ VaR-CVaR VNINDEX với 4 traces:
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
