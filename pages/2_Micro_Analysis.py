"""
pages/2_Micro_Analysis.py — Nhánh Phân tích Vi mô (Micro Analysis).
Hiện tại đang phát triển, sẽ có các công cụ phân tích vi mô sau này.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page

setup_page("Quant Platform — Micro Analysis")

st.title("🔬 Phân tích Vi mô (Micro Analysis)")
st.markdown("---")

st.info(
    "🚧 **Nhánh Micro Analysis đang được phát triển.**\n\n"
    "Các công cụ dự kiến sẽ bao gồm:\n"
    "- 📄 **Báo cáo tài chính doanh nghiệp** — Phân tích P/E, P/B, ROE, EPS các mã riêng lẻ\n"
    "- 📊 **Mô hình định giá DCF** — Chiết khấu dòng tiền cho từng cổ phiếu\n"
    "- 📈 **Kỹ thuật cá nhân** — Phân tích MA, RSI, MACD cho từng mã\n"
    "- 🎯 **Screening cổ phiếu** — Filter theo chỉ số tài chính\n\n"
    "Vui lòng quay lại sau khi các công cụ này được tích hợp.",
    icon="ℹ️"
)

st.markdown("---")
st.caption("© Quant Platform — Nhánh Micro Analysis")
