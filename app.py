"""
app.py — Trang chủ Streamlit.
"""
import streamlit as st
from pathlib import Path
from shared.page_layout import setup_page

setup_page("Quant Platform")

st.title("📊 Quant Platform")
st.markdown("Chọn công cụ từ menu bên trái để bắt đầu.")
st.markdown("Nếu Người Dùng Muốn Sử Dụng AI Đọc Kết Quả, Vui Lòng Tích Hợp API của Mô Hình Kimmi AI.")

from config import MARKET_DATA, DATA_LAKE, ROOT_DIR
from datetime import datetime, date

if MARKET_DATA.exists():
    mod = datetime.fromtimestamp(MARKET_DATA.stat().st_mtime)
    st.success(f"✅ Data lake sẵn sàng — cập nhật lần cuối: {mod.strftime('%d/%m/%Y %H:%M')}")
else:
    st.warning("⚠️ Data lake chưa có dữ liệu. Chạy `python update_data.py` trước.")

# AI CIO Report status
ai_report_path = DATA_LAKE / "daily_cache" / f"executive_summary_{date.today().strftime('%d%m%y')}.txt"
if ai_report_path.exists():
    ai_mod = datetime.fromtimestamp(ai_report_path.stat().st_mtime)
    st.success(f"✅ Report AI CIO đã sẵn sàng — {ai_mod.strftime('%d/%m/%Y %H:%M')}")
else:
    st.info("ℹ️ Chưa có report AI CIO. Chạy '🔥 Executive Summary (AI CIO)' để tạo.")

from fpdf import FPDF

def _create_pdf(text: str, path: str):
    import re
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    font_dir = ROOT_DIR / "fonts"
    pdf.add_font("DejaVu", "", str(font_dir / "DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu", "B", str(font_dir / "DejaVuSans-Bold.ttf"), uni=True)
    
    text_width = int(pdf.w - 20)  # 10mm margin each side — phải là int cho fpdf 1.7
    
    # Title
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(10, 10)
    pdf.cell(text_width, 10, f"Executive Summary Report — {date.today().strftime('%d/%m/%Y')}", border=0, ln=1, align="C")
    pdf.ln(5)
    
    # Body
    pdf.set_font("DejaVu", "", 11)
    for raw_line in text.split('\n'):
        line = raw_line.strip().replace('\t', ' ')
        line = re.sub(r'  +', ' ', line)
        if not line:
            pdf.ln(2)
            continue
        
        pdf.set_x(10)
        
        if line.startswith('#'):
            pdf.set_font("DejaVu", "B", 12)
            pdf.multi_cell(text_width, 7, line.lstrip('#').strip())
            pdf.set_font("DejaVu", "", 11)
        elif line.startswith('**') and line.endswith('**'):
            pdf.set_font("DejaVu", "B", 11)
            pdf.multi_cell(text_width, 6, line.replace('**', ''))
            pdf.set_font("DejaVu", "", 11)
        else:
            pdf.multi_cell(text_width, 6, line.replace('**', ''))
    pdf.output(path)

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("📄 Xuất PDF Report AI CIO", type="primary", use_container_width=True):
        # Ưu tiên session_state, fallback cache file
        report_text = st.session_state.get("cio_report", "")
        if not report_text:
            from shared.ai_cio import _read_cache
            report_text = _read_cache("executive_summary") or ""
        
        if not report_text:
            st.error("⚠️ Chưa có báo cáo AI CIO. Vui lòng chạy 'Executive Summary (AI CIO)' trước.")
        else:
            with st.spinner("Đang tạo PDF..."):
                try:
                    reports_dir = Path(__file__).resolve().parent / "reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    pdf_path = reports_dir / f"{date.today().strftime('%d%m%y')}_executive_summary.pdf"
                    _create_pdf(report_text, str(pdf_path))
                    st.success(f"Đã tạo PDF: {pdf_path.name}")
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            label="⬇️ Tải xuống PDF",
                            data=f,
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            use_container_width=True
                        )
                except Exception as e:
                    st.error(f"Lỗi tạo PDF: {e}")

with col2:
    if "show_cio_input" not in st.session_state:
        st.session_state.show_cio_input = False

    if st.button("🔥 Executive Summary (AI CIO)", type="primary", use_container_width=True):
        st.session_state.show_cio_input = True

if st.session_state.show_cio_input:
    with st.container(border=True):
        st.markdown("### 🤖 Kích hoạt AI CIO")
        cio_key = st.text_input("Nhập Kimi API Key:", type="password", key="cio_api_key")
        if st.button("🚀 Bắt đầu Tổng hợp", use_container_width=True):
            if not cio_key:
                st.error("Vui lòng nhập API Key!")
            else:
                with st.spinner("AI CIO đang tổng hợp 7 báo cáo và đưa ra quyết định... (Quá trình có thể mất 1-2 phút)"):
                    try:
                        from shared.ai_cio import run_executive_summary, _read_cache
                        
                        # Hiển thị nếu đã có cache
                        cached_sum = _read_cache("executive_summary")
                        if cached_sum:
                            st.session_state["cio_report"] = cached_sum
                            st.success("Tải kết quả AI CIO từ bộ nhớ tạm!")
                            st.markdown(cached_sum)
                        else:
                            summary_report = run_executive_summary(cio_key)
                            st.session_state["cio_report"] = summary_report
                            st.success("Hoàn thành Báo cáo Tổng lệnh!")
                            st.markdown(summary_report)
                    except Exception as e:
                        st.error(f"Lỗi khi chạy AI CIO: {e}")
