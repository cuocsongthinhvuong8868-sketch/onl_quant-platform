import datetime
import streamlit as st

def render_sidebar():
    """
    Sidebar cho VietNam VNIBOR tool.
    Returns:
        plot_start_date: datetime.date
    """
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Cấu hình VNIBOR")

    if st.sidebar.button("🗑️ Xóa Cache & Tải Lại", key="vnibor_clear_cache"):
        st.cache_data.clear()
        st.sidebar.success("Đã xóa bộ nhớ tạm!")

    st.sidebar.markdown("---")
    # Mặc định bắt đầu từ 2 năm trước cho đồ thị VNIBOR hiển thị đẹp
    default_start = datetime.date.today() - datetime.timedelta(days=730)
    plot_start_date = st.sidebar.date_input(
        "Ngày bắt đầu biểu đồ:",
        default_start,
        key="vnibor_plot_date",
    )

    return plot_start_date
