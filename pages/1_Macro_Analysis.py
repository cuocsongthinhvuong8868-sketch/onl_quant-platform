"""
pages/1_Macro_Analysis.py — Nhánh Phân tích Vĩ mô (Macro Analysis).
Hiện tại đang phát triển, sẽ có các công cụ phân tích vĩ mô sau này.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page

setup_page("Quant Platform — Macro Analysis")

st.title("📈 Phân tích Vĩ mô (Macro Analysis)")
st.markdown("---")

st.info(
    "🚧 **Nhánh Macro Analysis đang được phát triển.**\n\n"
    "Các công cụ dự kiến sẽ bao gồm:\n"
    "- 📊 **Lãi suất & Chính sách tiền tệ** — Phân tích tác động lãi suất điều hành, OMO, tín phiếu\n"
    "- 💱 **Tỷ giá & Dự trữ ngoại hối** — Đánh giá áp lực tỷ giá USD/VND\n"
    "- 📉 **Tăng trưởng GDP & CPI** — Tương quan vĩ mô và thị trường chứng khoán\n"
    "- 🌍 **Kinh tế toàn cầu** — Fed, lãi suất US, giá dầu, etc.\n\n"
    "Vui lòng quay lại sau khi các công cụ này được tích hợp.",
    icon="ℹ️"
)

st.markdown("---")
st.caption("© Quant Platform — Nhánh Macro Analysis")
