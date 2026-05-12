"""
ESR Monitor — UI Charts
========================
Plotly charts for SSI, pillars, PCA weights, and market state shading.
"""
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from tools.esr_monitor.quant.metrics import MARKET_STATES


def render_esr_chart(pillars: pd.DataFrame, ssi_result=None,
                     ma_period: int = 125, trend_ma_window: int = 200,
                     market_states: pd.Series = None, threshold: float = None):
    """
    Render the main SSI chart with optional HMM/state overlays.
    
    Parameters
    ----------
    pillars : DataFrame with at least 'INDEX_Close', 'SSI' columns
    ssi_result : SSIResult (provides pca_concentration for lower panel)
    ma_period : MA for VN30 overlay
    trend_ma_window : MA for trend filter
    market_states : pd.Series of 4-state labels
    threshold : HMM decision boundary
    """
    if 'SSI' not in pillars.columns or 'INDEX_Close' not in pillars.columns:
        st.warning("ESR chart requires SSI and INDEX_Close columns")
        return

    ssi_series = pillars['SSI'].dropna()
    idx_close = pillars['INDEX_Close'].dropna()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.04,
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    # SSI line
    fig.add_trace(
        go.Scatter(
            x=ssi_series.index, y=ssi_series,
            name='SSI', line=dict(color='darkred', width=2),
        ),
        row=1, col=1, secondary_y=False,
    )

    # VN30 close on secondary y-axis
    fig.add_trace(
        go.Scatter(
            x=idx_close.index, y=idx_close,
            name='VN30', line=dict(color='steelblue', width=1, dash='dot'),
        ),
        row=1, col=1, secondary_y=True,
    )

        # MA overlay
    ma = idx_close.rolling(ma_period).mean()
    fig.add_trace(
        go.Scatter(
            x=ma.index, y=ma,
            name=f'MA{ma_period}', line=dict(color='orange', width=1.5),
        ),
        row=1, col=1, secondary_y=True,
    )

    # Trend MA (luôn vẽ, không phụ thuộc HMM)
    trend_ma = idx_close.rolling(trend_ma_window, min_periods=max(trend_ma_window // 2, 20)).mean()
    if not trend_ma.dropna().empty:
        fig.add_trace(
            go.Scatter(
                x=trend_ma.index, y=trend_ma,
                name=f'Trend MA{trend_ma_window}',
                line=dict(color='gray', width=1, dash='longdash'),
            ),
            row=1, col=1, secondary_y=True,
        )

    # 4-state market regime shading (chỉ khi HMM bật)
    if market_states is not None and not market_states.dropna().empty:
        states_filled = market_states.fillna('UNKNOWN')
        change_id = (states_filled != states_filled.shift()).cumsum()
        for cid, block in states_filled.groupby(change_id):
            state_key = block.iloc[0]
            if state_key not in MARKET_STATES or state_key == 'HEALTHY':
                continue
            info = MARKET_STATES[state_key]
            fig.add_vrect(
                x0=block.index[0], x1=block.index[-1],
                fillcolor=info['fill_color'],
                opacity=0.18, layer="below", line_width=0,
                row=1, col=1,
            )

                # HMM threshold line
        if threshold is not None:
            fig.add_hline(
                y=threshold, line=dict(color='red', dash='dash', width=1.3),
                annotation_text=f"HMM threshold = {threshold:.3f}",
                annotation_position="top left", annotation_font_size=10,
                row=1, col=1, secondary_y=False,
            )
            fig.add_hrect(
                y0=threshold, y1=1.0,
                fillcolor="red", opacity=0.04, layer="below", line_width=0,
                row=1, col=1, secondary_y=False,
            )
    else:
        # Manual thresholds when HMM not available
        fig.add_hline(
            y=0.5, line=dict(color='orange', dash='dot', width=1),
            annotation_text="0.50 (WARNING)", annotation_position="top left",
            annotation_font_size=9,
            row=1, col=1, secondary_y=False,
        )
        fig.add_hline(
            y=0.8, line=dict(color='red', dash='dot', width=1),
            annotation_text="0.80 (CRITICAL)", annotation_position="top left",
            annotation_font_size=9,
            row=1, col=1, secondary_y=False,
        )

    # PCA concentration (lower panel)
    if ssi_result is not None:
        conc = ssi_result.pca_concentration
        fig.add_trace(
            go.Scatter(
                x=conc.index, y=conc,
                name='PCA EVR',
                line=dict(color='purple', width=1.5),
                fill='tozeroy', fillcolor='rgba(128,0,128,0.10)',
            ),
            row=2, col=1,
        )

    fig.update_yaxes(title_text="SSI", range=[0, 1], row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="VN30", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="EVR", range=[0, 1], row=2, col=1)
    fig.update_layout(height=680, hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig, use_container_width=True)


def render_pillar_diagnostics(pillars: pd.DataFrame, ssi_result):
    """Expander with pillar diagnostics tabs."""
    with st.expander("🔬 Pillar diagnostics"):
        tab1, tab2, tab3 = st.tabs(["Raw Pillars", "Expanding Ranks", "Weight Evolution"])
        with tab1:
            pillar_cols = [c for c in pillars.columns
                          if c.startswith('S_')]
            if pillar_cols:
                st.line_chart(pillars[pillar_cols])
        with tab2:
            st.line_chart(ssi_result.ranks)
        with tab3:
            st.line_chart(ssi_result.weights_history)
