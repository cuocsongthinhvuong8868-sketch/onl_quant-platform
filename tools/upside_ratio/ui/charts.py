from datetime import timedelta
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def render_history_chart(raw_upside, ma5_upside, raw_downside, ma5_downside, mu_up, mu_dn, df_index=None):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=raw_upside.index, y=raw_upside.values, name="Raw Upside", marker_color="rgba(37, 99, 235, 0.25)"), secondary_y=False)
    fig.add_trace(go.Bar(x=raw_downside.index, y=raw_downside.values, name="Raw Downside", marker_color="rgba(239, 68, 68, 0.25)"), secondary_y=False)
    fig.add_trace(go.Scatter(x=ma5_upside.index, y=ma5_upside.values, mode="lines", name="MA5 Upside", line=dict(color="#2563eb", width=2.5)), secondary_y=False)
    fig.add_trace(go.Scatter(x=ma5_downside.index, y=ma5_downside.values, mode="lines", name="MA5 Downside", line=dict(color="#ef4444", width=2.5)), secondary_y=False)

    if df_index is not None and not df_index.empty and "VNINDEX" in df_index.columns:
        plot_idx = df_index.loc[df_index.index.isin(ma5_upside.index)]
        if not plot_idx.empty:
            fig.add_trace(go.Scatter(x=plot_idx.index, y=plot_idx["VNINDEX"], mode="lines", name="VN-Index", line=dict(color="rgba(34, 197, 94, 0.9)", width=2, dash="dashdot")), secondary_y=True)

    fig.add_hline(y=mu_up * 100.0, line=dict(color="#2563eb", width=1, dash="dot"), secondary_y=False)
    fig.add_hline(y=mu_dn * 100.0, line=dict(color="#ef4444", width=1, dash="dot"), secondary_y=False)
    fig.update_layout(barmode="group", hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
    fig.update_yaxes(title_text="Breadth Ratio (%)", secondary_y=False)
    fig.update_yaxes(title_text="VN-Index", secondary_y=True, showgrid=False)
    st.plotly_chart(fig, use_container_width=True)


def _forecast_figure(title, color_main, color_band, past_dates, past_raw, past_ma5, future_dates, p5, p25, p50, p75, p95, mu):
    full_dates = past_dates + future_dates
    full_p5 = past_ma5 + list(p5)
    full_p25 = past_ma5 + list(p25)
    full_p50 = past_ma5 + list(p50)
    full_p75 = past_ma5 + list(p75)
    full_p95 = past_ma5 + list(p95)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=full_dates, y=full_p5, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=full_dates, y=full_p95, mode="lines", fill="tonexty", fillcolor=color_band[0], line=dict(width=0), name="Dải 90%"))
    fig.add_trace(go.Scatter(x=full_dates, y=full_p25, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=full_dates, y=full_p75, mode="lines", fill="tonexty", fillcolor=color_band[1], line=dict(width=0), name="Dải 50%"))
    fig.add_hline(y=mu * 100.0, line=dict(color="orange", width=1.5, dash="dot"), annotation_text=f"Long-run mu = {mu*100:.1f}%")
    fig.add_trace(go.Scatter(x=past_dates, y=past_raw, mode="lines+markers", name=f"Lịch sử ({title} raw)", line=dict(color=color_band[2], width=2)))
    fig.add_trace(go.Scatter(x=past_dates, y=past_ma5, mode="lines", name=f"MA5 {title}", line=dict(color=color_main, width=3)))
    fig.add_trace(go.Scatter(x=full_dates, y=full_p50, mode="lines", name="Ensemble Median", line=dict(color="#dc2626", width=3, dash="dash")))
    fig.update_layout(hovermode="x unified", yaxis_title=f"{title} Ratio (%)", margin=dict(l=20, r=20, t=30, b=20))
    fig.update_yaxes(range=[0, min(100, max(full_p95) * 1.2)])
    return fig


def render_projection_tabs(raw_upside, ma5_upside, raw_downside, ma5_downside, sim_days, up_tuple, dn_tuple):
    p5_up, p25_up, p50_up, p75_up, p95_up, _, mu_up, _, resid_beta_up = up_tuple
    p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, _, mu_dn, _, resid_beta_dn = dn_tuple

    last_date = raw_upside.index[-1]
    future_dates = pd.bdate_range(start=last_date + timedelta(days=1), periods=sim_days).date.tolist()
    n_tail = 10
    past_dates = list(raw_upside.index[-n_tail:])

    tab_up, tab_dn = st.tabs(["Du phong CẦU", "Du phong CUNG"])
    with tab_up:
        fig_up = _forecast_figure(
            "Upside", "#2563eb", ("rgba(250,160,60,0.15)", "rgba(250,160,60,0.35)", "rgba(37, 99, 235, 0.4)"),
            past_dates, list(raw_upside.values[-n_tail:]), list(ma5_upside.values[-n_tail:]), future_dates,
            p5_up, p25_up, p50_up, p75_up, p95_up, mu_up,
        )
        st.plotly_chart(fig_up, use_container_width=True)

    with tab_dn:
        fig_dn = _forecast_figure(
            "Downside", "#ef4444", ("rgba(239, 68, 68, 0.15)", "rgba(239, 68, 68, 0.35)", "rgba(239, 68, 68, 0.45)"),
            past_dates, list(raw_downside.values[-n_tail:]), list(ma5_downside.values[-n_tail:]), future_dates,
            p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, mu_dn,
        )
        st.plotly_chart(fig_dn, use_container_width=True)

    return resid_beta_up, resid_beta_dn


def render_diagnostics(raw_upside, raw_downside, resid_beta_up, resid_beta_dn):
    from scipy import stats

    with st.expander("Model Diagnostics", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            p_hist_up = np.clip(raw_upside.values / 100.0, 0.001, 0.999)
            a_up, b_up, _, _ = stats.beta.fit(p_hist_up, floc=0, fscale=1)
            ks_up, p_up = stats.kstest(p_hist_up, "beta", args=(a_up, b_up))
            st.metric("KS Upside", f"{ks_up:.3f}")
            st.metric("p-value Upside", f"{p_up:.3f}")
        with c2:
            p_hist_dn = np.clip(raw_downside.values / 100.0, 0.001, 0.999)
            a_dn, b_dn, _, _ = stats.beta.fit(p_hist_dn, floc=0, fscale=1)
            ks_dn, p_dn = stats.kstest(p_hist_dn, "beta", args=(a_dn, b_dn))
            st.metric("KS Downside", f"{ks_dn:.3f}")
            st.metric("p-value Downside", f"{p_dn:.3f}")

        st.caption(f"Residual beta upside std: {resid_beta_up.std() * 100:.2f}%")
        st.caption(f"Residual beta downside std: {resid_beta_dn.std() * 100:.2f}%")
