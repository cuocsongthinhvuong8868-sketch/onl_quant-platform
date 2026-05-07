import streamlit as st


def render_sidebar():
    st.sidebar.title("Dispersion Config")
    mc_window = st.sidebar.number_input("Rolling Covariance (ngày)", 20, 120, 30, 1)
    cov_refit_freq = st.sidebar.slider("Tần suất refit Cov (ngày)", 1, 20, 5, 1)
    zscore_window = st.sidebar.number_input("Rolling Z-Score (ngày)", 30, 252, 60, 10)
    dpi_window = st.sidebar.number_input("Cửa sổ đếm DPI (ngày)", 10, 60, 20, 1)

    st.sidebar.markdown("---")
    dpi_alert_thresh = st.sidebar.slider("Ngưỡng DPI Cảnh báo (%)", 30, 80, 50, 5)
    corr_dist_thresh = st.sidebar.slider("Tương quan Phân phối đỉnh (<)", 0.05, 0.35, 0.20, 0.01)
    corr_cap_thresh = st.sidebar.slider("Tương quan Đáy hoảng loạn (>)", 0.25, 0.60, 0.35, 0.01)

    return {
        "mc_window": int(mc_window),
        "cov_refit_freq": int(cov_refit_freq),
        "zscore_window": int(zscore_window),
        "dpi_window": int(dpi_window),
        "dpi_alert_thresh": float(dpi_alert_thresh),
        "corr_dist_thresh": float(corr_dist_thresh),
        "corr_cap_thresh": float(corr_cap_thresh),
    }
