import streamlit as st


def render_sidebar() -> dict:
    with st.sidebar:
        st.header("Upside/Downside Config")
        upside_x = st.number_input("Ngưỡng Upside X (%)", value=2.0, step=0.5)
        downside_y = st.number_input("Ngưỡng Downside Y (%)", value=-2.0, step=0.5)
        lookback_days = st.slider("Khung lịch sử (ngày)", min_value=30, max_value=250, value=90)
        sim_days = st.slider("Số phiên giả lập", min_value=5, max_value=40, value=10)

    return {
        "upside_x": float(upside_x),
        "downside_y": float(downside_y),
        "lookback_days": int(lookback_days),
        "sim_days": int(sim_days),
    }
