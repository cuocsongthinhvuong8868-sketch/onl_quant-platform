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
        "kimi-2.6-local": {
            "display": "Kimi 2.6 Local",
            "api_model": "kimi-k2.6",
            "base_url": "http://127.0.0.1:5001/v1",
        },
        "chatgpt-local": {
            "display": "ChatGPT Local",
            "api_model": "gpt-5.5",
            "base_url": "http://127.0.0.1:5003/v1",
        },
    }


K_OPTIONS = {
    "Siêu nới lỏng (0.3)": 0.3,
    "Nới lỏng (0.5)": 0.5,
    "Nới lỏng (0.7)": 0.7,
    "Tiêu chuẩn (1.0)": 1.0,
    "Cảnh báo (1.25)": 1.25,
    "Stress (1.5)": 1.5,
    "Khủng hoảng (2.0)": 2.0,
}


def render_sidebar() -> dict:
    with st.sidebar:
        st.header("Cài đặt Biến Số Căn Bản")
        selected_k = st.selectbox("Chọn Viễn cảnh (Hệ số K):", list(K_OPTIONS.keys()), index=3)
        coe_input = st.number_input("Cost of Equity (COE) %:", min_value=1.0, max_value=30.0, value=13.0, step=0.5)

        st.markdown("---")
        st.header("Kiểm tra Kịch bản")
        bvps_change_pct = st.number_input("Thay đổi BVPS (%):", min_value=-99.0, max_value=200.0, value=0.0, step=1.0)
        pb_penalty_pct = st.number_input("Mức phạt P/B (%):", min_value=0.0, max_value=200.0, value=0.0, step=1.0)

        st.markdown("---")
        st.subheader("🧠 Tích hợp AI")
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
        "selected_k": selected_k,
        "k_value": K_OPTIONS[selected_k],
        "coe_decimal": coe_input / 100.0,
        "coe_input": coe_input,
        "bvps_change_pct": bvps_change_pct,
        "pb_penalty_pct": pb_penalty_pct,
        "ai_provider": ai_provider,
        "api_key": api_key,
    }
