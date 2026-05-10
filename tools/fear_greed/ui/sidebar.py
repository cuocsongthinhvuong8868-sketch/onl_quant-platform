import logging
import streamlit as st
from config import AI_PROVIDER_MAP

logger = logging.getLogger(__name__)


def render_sidebar() -> dict:
    """
    Render sidebar controls, trả về dict các tham số người dùng chọn.

    Keys
    ----
    window_size : int
    """
    st.sidebar.title("⚙️ Cài đặt")

    window_size = st.sidebar.slider(
        "⏳ Quant Window (ngày)",
        min_value=20, max_value=60, value=60, step=10,
        help="Cửa sổ cuộn cho Skewness, Beta, CSV và EWM halflife Correlation.",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🧠 Tích hợp AI")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
    )
    api_key = st.sidebar.text_input("API Key (Bảo mật)", type="password", value="", placeholder="sk-...")

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "**Mô hình** \n"
        "- Market Factor: PCA (PC1) \n"
        "- Volatility: EGARCH(1,1,1) Skewed-T \n"
        "- Scaling: Rolling Percentile Rank (252 ngày) \n"
        "- Skewness: Kelly non-parametric"
    )

    return {"window_size": window_size, "ai_provider": ai_provider, "api_key": api_key}
