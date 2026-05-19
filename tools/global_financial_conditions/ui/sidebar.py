import datetime
import streamlit as st


def render_sidebar() -> datetime.date:
    """
    Sidebar GFCM: slider 'Lùi bao nhiêu năm?' + nút clear cache.

    Returns
    -------
    plot_start_date : datetime.date
        Ngày bắt đầu hiển thị biểu đồ (today − n_years).
    """
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Tham số GFCM")

    if st.sidebar.button("🗑️ Xóa Cache & Tải Lại", key="gfcm_clear_cache"):
        st.cache_data.clear()
        st.sidebar.success("Đã xóa bộ nhớ tạm!")

    st.sidebar.markdown("---")
    n_years = st.sidebar.slider(
        "📅 Lùi bao nhiêu năm?",
        min_value=1,
        max_value=22,
        value=3,
        step=1,
        key="gfcm_n_years",
        help="Khoảng thời gian hiển thị biểu đồ tính từ hôm nay lùi về quá khứ.",
    )
    today = datetime.date.today()
    plot_start_date = datetime.date(today.year - n_years, today.month, today.day) \
        if today.month != 2 or today.day != 29 else datetime.date(today.year - n_years, 3, 1)
    st.sidebar.caption(f"Hiển thị từ **{plot_start_date.strftime('%d/%m/%Y')}** đến nay.")

    return plot_start_date
