import logging
import streamlit as st
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
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }

logger = logging.getLogger(__name__)


def render_sidebar() -> dict:
    """
    Render sidebar controls, trả về dict các tham số người dùng chọn.

    Keys
    ----
    window_size : int
    """
    st.sidebar.title("⚙️ Cài đặt")

    time_interval = st.sidebar.selectbox(
        "📅 Khung thời gian hiển thị",
        options=["1M", "3M", "6M", "YTD", "1Y", "All"],
        index=4,
    )

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

    return {"window_size": window_size, "time_interval": time_interval, "ai_provider": ai_provider, "api_key": api_key}