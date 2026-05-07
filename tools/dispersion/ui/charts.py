import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def _add_regime_shading(fig, regime_series):
    for state, color in [("DISTRIBUTION_PEAK", "red"), ("CAPITULATION_BOTTOM", "green")]:
        mask = regime_series == state
        if not mask.any():
            continue
        changes = mask.astype(int).diff().fillna(0)
        starts = changes[changes == 1].index
        ends = changes[changes == -1].index
        if mask.iloc[0]:
            starts = starts.insert(0, mask.index[0])
        if mask.iloc[-1]:
            ends = ends.append(type(ends)([mask.index[-1]]))
        for s, e in zip(starts, ends):
            if s <= e:
                fig.add_vrect(x0=s, x1=e, fillcolor=color, opacity=0.10, layer="below", line_width=0)


def render_main_chart(df_metrics, dpi_alert_thresh: float, corr_dist_thresh: float, corr_cap_thresh: float):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df_metrics.index, y=df_metrics["DPI"], mode="lines", name="DPI", line=dict(color="#ef4444", width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_metrics.index, y=df_metrics["Ledoit_Correlation"], mode="lines", name="Corr", line=dict(color="#2563eb", width=2)), secondary_y=True)
    _add_regime_shading(fig, df_metrics["Macro_Regime"])

    # Threshold lines
    fig.add_hline(
        y=dpi_alert_thresh,
        line=dict(color="#ef4444", width=1.5, dash="dash"),
        annotation_text=f"DPI Thresh {dpi_alert_thresh:.0f}%",
        annotation_position="top left",
        secondary_y=False,
    )
    fig.add_hline(
        y=corr_dist_thresh,
        line=dict(color="#f59e0b", width=1.5, dash="dot"),
        annotation_text=f"Dist Corr < {corr_dist_thresh:.2f}",
        annotation_position="bottom left",
        secondary_y=True,
    )
    fig.add_hline(
        y=corr_cap_thresh,
        line=dict(color="#16a34a", width=1.5, dash="dot"),
        annotation_text=f"Cap Corr > {corr_cap_thresh:.2f}",
        annotation_position="top right",
        secondary_y=True,
    )
    fig.update_layout(hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
    fig.update_yaxes(title_text="DPI (%)", secondary_y=False)
    fig.update_yaxes(title_text="Correlation", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)
