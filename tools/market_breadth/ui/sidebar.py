from datetime import timedelta
import pandas as pd
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


def render_sidebar(df_breadth: pd.DataFrame):
    st.sidebar.header("History Measurement")

    min_date = df_breadth.index.min().date()
    max_date = df_breadth.index.max().date()

    default_start = max(min_date, max_date - timedelta(days=365))
    start_date = st.sidebar.date_input("Từ ngày", value=default_start, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("Đến ngày", value=max_date, min_value=min_date, max_value=max_date)

    if start_date > end_date:
        st.sidebar.error("'Từ ngày' phải trước hoặc bằng 'Đến ngày'.")

    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="mb_ai_provider",
    )
    api_key = st.sidebar.text_input("API Key", type="password", key="mb_api_key")

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    return start_date, end_date, start_dt, end_dt, ai_provider, api_key