import streamlit as st
import datetime

def render_sidebar():
    st.sidebar.markdown("---")
    if st.sidebar.button("🗑️ Xóa Cache & Tải Lại Dữ Liệu", key="var_cvar_clear_cache"):
        st.cache_data.clear()
        st.sidebar.success("Đã xóa bộ nhớ tạm!")
        
    st.sidebar.markdown("---")
    plot_start_date = st.sidebar.date_input(
        "Ngày bắt đầu biểu đồ:",
        datetime.date(2020, 1, 1),
        key="var_cvar_plot_date"
    )
    
    return plot_start_date
