import streamlit as st
import datetime

def render_sidebar():
    st.sidebar.markdown("---")
    if st.sidebar.button("🗑️ Xóa Cache & Tải Lại Dữ Liệu", key="va_res_clear_cache"):
        st.cache_data.clear()
        st.sidebar.success("Đã xóa bộ nhớ tạm!")
        
    st.sidebar.markdown("---")
    menu = st.sidebar.radio("Chọn chức năng:", ["A. Phân tích Cổ phiếu Riêng lẻ", "B. Cảnh báo Sập gãy (Rổ VN30)", "C. Cảnh báo Định giá sai Rủi ro (Toàn thị trường)"], key="va_res_menu")
    
    plot_start_date = st.sidebar.date_input("Ngày bắt đầu biểu đồ:", datetime.date(2019, 1, 1), key="va_res_plot_date")
    
    return menu, plot_start_date
