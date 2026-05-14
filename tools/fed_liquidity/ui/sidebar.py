import datetime
import streamlit as st


def render_sidebar():
    """
    Sidebar cho Fed Liquidity Monitor.

    Returns
    -------
    plot_start_date : datetime.date
        Ngày bắt đầu hiển thị biểu đồ.
    """
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Tham số Fed Liquidity")

    if st.sidebar.button("🗑️ Xóa Cache & Tải Lại", key="fed_liq_clear_cache"):
        st.cache_data.clear()
        st.sidebar.success("Đã xóa bộ nhớ tạm!")

    st.sidebar.markdown("---")
    plot_start_date = st.sidebar.date_input(
        "Ngày bắt đầu biểu đồ:",
        datetime.date(2020, 1, 1),
        key="fed_liq_plot_date",
    )

    return plot_start_date
