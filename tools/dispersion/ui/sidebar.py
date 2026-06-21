import streamlit as st
from shared.api_key_helper import resolve_api_key
try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {
            "display": "Kimi 2.6",
            "api_model": "kimi-k2.6",
            "base_url": "https://api.moonshot.ai/v1",
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
        },
    }


def render_sidebar():
    st.sidebar.title("Dispersion Config")
    mc_window = st.sidebar.number_input("Rolling Covariance (ngày)", 20, 120, 30, 1)
    cov_refit_freq = st.sidebar.slider("Tần suất refit Cov (ngày)", 1, 20, 5, 1)
    zscore_type = st.sidebar.radio("Z-score baseline type:", ["Rolling", "EWMA"], index=0)
    zscore_window = st.sidebar.number_input("Rolling Z-Score (ngày)", 30, 252, 60, 10)
    dpi_window = st.sidebar.number_input("Cửa sổ đếm DPI (ngày)", 10, 60, 60, 1)

    st.sidebar.markdown("---")
    recent_window_2d = st.sidebar.number_input("Highlight Recent 2D (ngày):", 5, 90, 30, 5)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🧠 Tích hợp AI")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
    )
    api_key_raw = st.sidebar.text_input("API Key (hoặc shortcut 4 số):", type="password", value="", placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    return {
        "mc_window": int(mc_window),
        "cov_refit_freq": int(cov_refit_freq),
        "zscore_type": zscore_type,
        "zscore_window": int(zscore_window),
        "dpi_window": int(dpi_window),
        "recent_window_2d": int(recent_window_2d),
        "ai_provider": ai_provider,
        "api_key": api_key,
    }

