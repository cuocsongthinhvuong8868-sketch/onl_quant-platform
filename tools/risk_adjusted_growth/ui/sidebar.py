import streamlit as st


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
        coe_input = st.number_input("Cost of Equity (COE) %:", min_value=1.0, max_value=30.0, value=12.0, step=0.5)

        st.markdown("---")
        st.header("Kiểm tra Kịch bản")
        bvps_change_pct = st.number_input("Thay đổi BVPS (%):", min_value=-99.0, max_value=200.0, value=0.0, step=1.0)
        pb_penalty_pct = st.number_input("Mức phạt P/B (%):", min_value=0.0, max_value=200.0, value=0.0, step=1.0)

    return {
        "selected_k": selected_k,
        "k_value": K_OPTIONS[selected_k],
        "coe_decimal": coe_input / 100.0,
        "coe_input": coe_input,
        "bvps_change_pct": bvps_change_pct,
        "pb_penalty_pct": pb_penalty_pct,
    }
