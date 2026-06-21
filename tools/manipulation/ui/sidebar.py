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


def render_sidebar(default_threshold: float):
    st.sidebar.header("Manipulation Config")
    window = st.sidebar.number_input("Rolling Window", min_value=10, max_value=252, value=60, step=1)
    threshold = st.sidebar.slider("Ngưỡng Sai số (Δ)", min_value=0.05, max_value=0.50, value=float(round(default_threshold, 2)), step=0.01)
    
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
    
    return {"window": int(window), "threshold": float(threshold), "ai_provider": ai_provider, "api_key": api_key}

