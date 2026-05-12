from datetime import datetime, timedelta
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
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }


def render_sidebar(df_close: object = None) -> dict:
    with st.sidebar:
        st.header("⚙️ Cấu hình Model")
        upside_x = st.number_input("Ngưỡng Upside X (%)", value=2.0, step=0.5)
        downside_y = st.number_input("Ngưỡng Downside Y (%)", value=-2.0, step=0.5)
        lookback_days = st.slider("Khung lịch sử (ngày)", min_value=30, max_value=250, value=90)
        sim_days = st.slider("Số phiên giả lập", min_value=5, max_value=40, value=10)

        st.divider()
        st.header("⏳ Cỗ máy thởi gian (Backtest)")
        run_mode = st.radio(
            "Chế độ chạy:",
            ["Live (Hiện tại)", "Backtest (Quá khứ)"],
            horizontal=True,
        )

        backtest_date = None
        if run_mode == "Backtest (Quá khứ)" and df_close is not None and not df_close.empty:
            max_bt_date = df_close.index.max().date() - timedelta(days=sim_days)
            min_bt_date = df_close.index.min().date() + timedelta(days=lookback_days + 10)
            if max_bt_date > min_bt_date:
                backtest_date = st.date_input(
                    "Chọn ngày muốn quay về:",
                    value=max_bt_date,
                    min_value=min_bt_date,
                    max_value=max_bt_date,
                )

        st.divider()
        st.subheader("🧠 Tích hợp AI")
        ai_provider = st.selectbox(
            "🤖 Chọn Model AI",
            options=list(AI_PROVIDER_MAP.keys()),
            format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
            index=0,
        )
        api_key_raw = st.text_input("API Key (hoặc shortcut 4 số):", type="password", value="", placeholder="sk-... hoặc 4 số",
            help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
        api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw)
        if api_key_err:
            st.error(api_key_msg)
        elif api_key_msg:
            st.success(api_key_msg)

    return {
        "upside_x": float(upside_x),
        "downside_y": float(downside_y),
        "lookback_days": int(lookback_days),
        "sim_days": int(sim_days),
        "run_mode": str(run_mode),
        "backtest_date": backtest_date,
        "ai_provider": ai_provider,
        "api_key": api_key,
    }