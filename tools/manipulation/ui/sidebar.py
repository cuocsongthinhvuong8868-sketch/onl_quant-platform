import streamlit as st
from config import AI_PROVIDER_MAP


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
    api_key = st.sidebar.text_input("API Key (Bảo mật)", type="password", value="", placeholder="sk-...")
    
    return {"window": int(window), "threshold": float(threshold), "ai_provider": ai_provider, "api_key": api_key}

