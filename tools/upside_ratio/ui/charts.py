from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import scipy.stats as stats
import streamlit as st


def render_history_chart(raw_upside, ma5_upside, raw_downside, ma5_downside, mu_up, mu_dn, df_index=None):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=raw_upside.index, y=raw_upside.values,
            name="Raw Upside (Cầu)", marker_color="rgba(37, 99, 235, 0.25)",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=raw_downside.index, y=raw_downside.values,
            name="Raw Downside (Cung)", marker_color="rgba(239, 68, 68, 0.25)",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=ma5_upside.index, y=ma5_upside.values, mode="lines",
            name="MA5 Upside", line=dict(color="#2563eb", width=2.5),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=ma5_downside.index, y=ma5_downside.values, mode="lines",
            name="MA5 Downside", line=dict(color="#ef4444", width=2.5),
        ),
        secondary_y=False,
    )

    if df_index is not None and not df_index.empty and "VNINDEX" in df_index.columns:
        plot_idx = df_index.loc[df_index.index.isin(ma5_upside.index)]
        if not plot_idx.empty:
            fig.add_trace(
                go.Scatter(
                    x=plot_idx.index, y=plot_idx["VNINDEX"], mode="lines",
                    name="VN-Index", line=dict(color="rgba(34, 197, 94, 0.9)", width=2, dash="dashdot"),
                ),
                secondary_y=True,
            )

    fig.add_hline(y=mu_up * 100.0, line=dict(color="#2563eb", width=1, dash="dot"), secondary_y=False)
    fig.add_hline(y=mu_dn * 100.0, line=dict(color="#ef4444", width=1, dash="dot"), secondary_y=False)
    fig.update_layout(
        barmode="group", hovermode="x unified",
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Breadth Ratio (%)", secondary_y=False)
    fig.update_yaxes(title_text="VN-Index", secondary_y=True, showgrid=False)
    st.plotly_chart(fig, use_container_width=True)


def _forecast_figure(
    title, color_main, color_band,
    past_dates, past_raw, past_ma5, future_dates,
    p5, p25, p50, p75, p95, mu,
    actual_ma5=None, backtest_date=None,
):
    full_dates = past_dates + future_dates
    full_p5 = past_ma5 + list(p5)
    full_p25 = past_ma5 + list(p25)
    full_p50 = past_ma5 + list(p50)
    full_p75 = past_ma5 + list(p75)
    full_p95 = past_ma5 + list(p95)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=full_dates, y=full_p5, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=full_dates, y=full_p95, mode="lines", fill="tonexty",
        fillcolor=color_band[0], line=dict(width=0), name="Dải 90% (Fat-Tail)",
    ))
    fig.add_trace(go.Scatter(x=full_dates, y=full_p25, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=full_dates, y=full_p75, mode="lines", fill="tonexty",
        fillcolor=color_band[1], line=dict(width=0), name="Dải 50% (Core)",
    ))
    fig.add_hline(
        y=mu * 100.0, line=dict(color="orange", width=1.5, dash="dot"),
        annotation_text=f"Long-run μ = {mu*100:.1f}%",
    )
    fig.add_trace(go.Scatter(
        x=past_dates, y=past_raw, mode="lines+markers",
        name=f"Lịch sử ({title} raw)", line=dict(color=color_band[2], width=2),
    ))
    fig.add_trace(go.Scatter(
        x=past_dates, y=past_ma5, mode="lines",
        name=f"MA5 {title}", line=dict(color=color_main, width=3),
    ))
    fig.add_trace(go.Scatter(
        x=full_dates, y=full_p50, mode="lines",
        name="Ensemble Median", line=dict(color="#dc2626", width=3, dash="dash"),
    ))

    # Backtest overlay
    if actual_ma5 is not None and not actual_ma5.empty:
        fig.add_trace(go.Scatter(
            x=actual_ma5.index, y=actual_ma5.values, mode="lines+markers",
            name=f"🚀 THỰC TẾ {title.upper()} DIỄN RA",
            line=dict(color="black", width=4),
        ))
    if backtest_date is not None:
        fig.add_vline(
            x=pd.Timestamp(backtest_date).timestamp() * 1000,
            line=dict(color="black", dash="dash"),
            annotation_text="Ngày Backtest",
        )

    fig.update_layout(
        hovermode="x unified", yaxis_title=f"{title} Ratio (%)",
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(range=[0, min(100, max(full_p95) * 1.2)])
    return fig


def render_projection_tabs(
    raw_upside, ma5_upside, raw_downside, ma5_downside, sim_days,
    up_tuple, dn_tuple,
    actual_up=None, actual_dn=None, backtest_date=None,
):
    p5_up, p25_up, p50_up, p75_up, p95_up, _, mu_up, _, resid_beta_up = up_tuple
    p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, _, mu_dn, _, resid_beta_dn = dn_tuple

    last_date = raw_upside.index[-1]
    future_dates = pd.bdate_range(start=last_date + timedelta(days=1), periods=sim_days).date.tolist()
    n_tail = 10
    past_dates = list(raw_upside.index[-n_tail:])

    tab_up, tab_dn = st.tabs(["📈 Dự phóng CẦU (Upside)", "🩸 Dự phóng CUNG (Downside)"])
    with tab_up:
        fig_up = _forecast_figure(
            "Upside", "#2563eb",
            ("rgba(250,160,60,0.15)", "rgba(250,160,60,0.35)", "rgba(37, 99, 235, 0.4)"),
            past_dates, list(raw_upside.values[-n_tail:]), list(ma5_upside.values[-n_tail:]),
            future_dates, p5_up, p25_up, p50_up, p75_up, p95_up, mu_up,
            actual_ma5=actual_up, backtest_date=backtest_date,
        )
        st.plotly_chart(fig_up, use_container_width=True)

    with tab_dn:
        fig_dn = _forecast_figure(
            "Downside", "#ef4444",
            ("rgba(239, 68, 68, 0.15)", "rgba(239, 68, 68, 0.35)", "rgba(239, 68, 68, 0.45)"),
            past_dates, list(raw_downside.values[-n_tail:]), list(ma5_downside.values[-n_tail:]),
            future_dates, p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, mu_dn,
            actual_ma5=actual_dn, backtest_date=backtest_date,
        )
        st.plotly_chart(fig_dn, use_container_width=True)

    return resid_beta_up, resid_beta_dn


def render_diagnostics(raw_upside, raw_downside, resid_beta_up, resid_beta_dn):
    with st.expander("🔬 Model Diagnostics — Beta fit & Residuals", expanded=False):
        tab1, tab2 = st.tabs(["📈 Chuẩn đoán Upside", "📉 Chuẩn đoán Downside"])

        with tab1:
            col1, col2 = st.columns(2)
            p_hist_up = np.clip(raw_upside.values / 100.0, 0.001, 0.999)
            a_fit_up, b_fit_up, _, _ = stats.beta.fit(p_hist_up, floc=0, fscale=1)

            with col1:
                fig_hist_up = go.Figure()
                fig_hist_up.add_trace(go.Histogram(
                    x=raw_upside.values, nbinsx=30, histnorm="probability density",
                    marker_color="#3b82f6", opacity=0.65, name="Thực tế",
                ))
                x_range = np.linspace(0.5, 99.5, 300)
                beta_pdf = stats.beta.pdf(x_range / 100, a_fit_up, b_fit_up) / 100
                fig_hist_up.add_trace(go.Scatter(
                    x=x_range, y=beta_pdf, mode="lines",
                    line=dict(color="orange", width=2.5), name="Beta fit",
                ))
                fig_hist_up.update_layout(
                    xaxis_title="Upside Ratio (%)", margin=dict(l=10, r=10, t=20, b=20),
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_hist_up, use_container_width=True)

            with col2:
                fig_resid_up = go.Figure()
                fig_resid_up.add_trace(go.Histogram(
                    x=resid_beta_up * 100, nbinsx=30, histnorm="probability density",
                    marker_color="#8b5cf6", opacity=0.65, name="Sốc Thực tế",
                ))
                xr = np.linspace(resid_beta_up.min() * 100, resid_beta_up.max() * 100, 300)
                norm_pdf = stats.norm.pdf(xr, resid_beta_up.mean() * 100, resid_beta_up.std() * 100)
                fig_resid_up.add_trace(go.Scatter(
                    x=xr, y=norm_pdf, mode="lines",
                    line=dict(color="red", width=2, dash="dash"), name="Normal",
                ))
                fig_resid_up.update_layout(
                    xaxis_title="Residual (%)", margin=dict(l=10, r=10, t=20, b=20),
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_resid_up, use_container_width=True)

            ks_stat_up, ks_pval_up = stats.kstest(p_hist_up, "beta", args=(a_fit_up, b_fit_up))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("KS Statistic", f"{ks_stat_up:.3f}")
            c2.metric("KS p-value", f"{ks_pval_up:.3f}")
            c3.metric("Residual std", f"{resid_beta_up.std() * 100:.2f}%")
            c4.metric("Beta (α, β)", f"{a_fit_up:.2f}, {b_fit_up:.2f}")

        with tab2:
            col3, col4 = st.columns(2)
            p_hist_dn = np.clip(raw_downside.values / 100.0, 0.001, 0.999)
            a_fit_dn, b_fit_dn, _, _ = stats.beta.fit(p_hist_dn, floc=0, fscale=1)

            with col3:
                fig_hist_dn = go.Figure()
                fig_hist_dn.add_trace(go.Histogram(
                    x=raw_downside.values, nbinsx=30, histnorm="probability density",
                    marker_color="#ef4444", opacity=0.65, name="Thực tế",
                ))
                beta_pdf_dn = stats.beta.pdf(x_range / 100, a_fit_dn, b_fit_dn) / 100
                fig_hist_dn.add_trace(go.Scatter(
                    x=x_range, y=beta_pdf_dn, mode="lines",
                    line=dict(color="orange", width=2.5), name="Beta fit",
                ))
                fig_hist_dn.update_layout(
                    xaxis_title="Downside Ratio (%)", margin=dict(l=10, r=10, t=20, b=20),
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_hist_dn, use_container_width=True)

            with col4:
                fig_resid_dn = go.Figure()
                fig_resid_dn.add_trace(go.Histogram(
                    x=resid_beta_dn * 100, nbinsx=30, histnorm="probability density",
                    marker_color="#f97316", opacity=0.65, name="Sốc Thực tế",
                ))
                xr_dn = np.linspace(resid_beta_dn.min() * 100, resid_beta_dn.max() * 100, 300)
                norm_pdf_dn = stats.norm.pdf(xr_dn, resid_beta_dn.mean() * 100, resid_beta_dn.std() * 100)
                fig_resid_dn.add_trace(go.Scatter(
                    x=xr_dn, y=norm_pdf_dn, mode="lines",
                    line=dict(color="red", width=2, dash="dash"), name="Normal",
                ))
                fig_resid_dn.update_layout(
                    xaxis_title="Residual (%)", margin=dict(l=10, r=10, t=20, b=20),
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_resid_dn, use_container_width=True)

            ks_stat_dn, ks_pval_dn = stats.kstest(p_hist_dn, "beta", args=(a_fit_dn, b_fit_dn))
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("KS Statistic", f"{ks_stat_dn:.3f}")
            c6.metric("KS p-value", f"{ks_pval_dn:.3f}")
            c7.metric("Residual std", f"{resid_beta_dn.std() * 100:.2f}%")
            c8.metric("Beta (α, β)", f"{a_fit_dn:.2f}, {b_fit_dn:.2f}")
