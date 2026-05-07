"""
app.py — Trang chủ Streamlit.
"""
import streamlit as st

st.set_page_config(
    page_title="Quant Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 Quant Platform")
st.markdown("Chọn công cụ từ menu bên trái để bắt đầu.")

from config import MARKET_DATA
from datetime import datetime

if MARKET_DATA.exists():
    mod = datetime.fromtimestamp(MARKET_DATA.stat().st_mtime)
    st.success(f"✅ Data lake sẵn sàng — cập nhật lần cuối: {mod.strftime('%d/%m/%Y %H:%M')}")
else:
    st.warning("⚠️ Data lake chưa có dữ liệu trong repo.")

st.info(
    "Bản `onl_quant_platform` chạy theo chế độ read-only trên Streamlit Cloud. "
    "Muốn cập nhật dữ liệu, chạy pipeline update ở local rồi commit lại thư mục `data_lake` lên GitHub."
)
