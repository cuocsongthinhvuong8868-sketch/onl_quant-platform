"""
app.py — Trang chủ Streamlit.
"""
import os
import streamlit as st
from pathlib import Path
from shared.page_layout import setup_page

setup_page("Quant Platform")

st.title("📊 Quant Platform")
st.markdown("Chọn công cụ từ menu bên trái để bắt đầu.")
st.markdown("Nếu Người Dùng Muốn Sử Dụng AI Đọc Kết Quả, Vui Lòng Tích Hợp API của Mô Hình Kimmi AI Hoặc Deepseek AI .")

from config import MARKET_DATA, DATA_LAKE, ROOT_DIR
try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {
            "display": "Kimi 2.6",
            "api_model": "kimi-k2.6",
            "base_url": "https://api.moonshot.ai/v1",
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
from datetime import datetime, date

if MARKET_DATA.exists():
    mod = datetime.fromtimestamp(MARKET_DATA.stat().st_mtime)
    st.success(f"✅ Data lake sẵn sàng — cập nhật lần cuối: {mod.strftime('%d/%m/%Y %H:%M')}")
else:
    st.warning("⚠️ Data lake chưa có dữ liệu. Chạy `python update_data.py` trước.")

# ── AI CIO Report status (quét tất cả provider) ──
TODAY_STR = date.today().strftime('%d%m%y')
_available_cio = []
for _pk, _pv in AI_PROVIDER_MAP.items():
    _rp = DATA_LAKE / "daily_cache" / f"executive_summary_{_pk}_{TODAY_STR}.txt"
    if _rp.exists():
        _rm = datetime.fromtimestamp(_rp.stat().st_mtime)
        _available_cio.append((_pk, _pv["display"], _rm))

if _available_cio:
    for _pk, _disp, _rm in _available_cio:
        st.success(f"✅ Report AI CIO ({_disp}) đã sẵn sàng — {_rm.strftime('%d/%m/%Y %H:%M')}")
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

# ── Xuất PDF AI CIO (cho phép chọn model khi có nhiều bản) ──
if "cio_pdf_choice" not in st.session_state:
    st.session_state.cio_pdf_choice = None

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("📄 Xuất PDF Report AI CIO", type="primary", use_container_width=True):
        # Nếu chỉ có 1 bản → dùng luôn; nếu nhiều bản → hiện dropdown chọn
        if len(_available_cio) == 1:
            st.session_state.cio_pdf_choice = _available_cio[0][0]
        elif len(_available_cio) > 1:
            st.session_state.cio_pdf_choice = "__choose__"
        else:
            st.session_state.cio_pdf_choice = None
            st.error("⚠️ Chưa có báo cáo AI CIO. Vui lòng chạy 'Executive Summary (AI CIO)' trước.")

# Hiện dropdown chọn model khi có nhiều bản báo cáo
if st.session_state.cio_pdf_choice == "__choose__" and len(_available_cio) > 1:
    with st.container(border=True):
        st.markdown("### 📄 Chọn bản báo cáo để xuất PDF")
        chosen = st.selectbox(
            "Model AI:",
            options=[pk for pk, _, _ in _available_cio],
            format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
            key="cio_pdf_model_select",
        )
        if st.button("⬇️ Tạo & Tải PDF", use_container_width=True):
            st.session_state.cio_pdf_choice = chosen

# Thực hiện tạo PDF khi đã có lựa chọn hợp lệ
if st.session_state.cio_pdf_choice and st.session_state.cio_pdf_choice != "__choose__":
    cio_provider = st.session_state.cio_pdf_choice
    # Ưu tiên session_state nếu khớp provider đang chọn
    report_text = ""
    if st.session_state.get("cio_provider") == cio_provider:
        report_text = st.session_state.get("cio_report", "")
    if not report_text:
        from shared.ai_cio import _read_cache
        report_text = _read_cache("executive_summary", cio_provider) or ""

    if not report_text:
        st.error("⚠️ Không đọc được nội dung báo cáo. Vui lòng chạy lại Executive Summary.")
        st.session_state.cio_pdf_choice = None
    else:
        with st.spinner("Đang tạo PDF..."):
            try:
                reports_dir = Path(__file__).resolve().parent / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                provider_prefix = cio_provider.replace("-", "_")
                pdf_path = reports_dir / f"{date.today().strftime('%d%m%y')}_{provider_prefix}_executive_summary.pdf"
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
        st.session_state.cio_pdf_choice = None

with col2:
    if "show_cio_input" not in st.session_state:
        st.session_state.show_cio_input = False

    if st.button("🔥 Executive Summary (AI CIO)", type="primary", use_container_width=True):
        st.session_state.show_cio_input = True

if "cio_force_refresh" not in st.session_state:
    st.session_state.cio_force_refresh = False

if st.session_state.show_cio_input:
    with st.container(border=True):
        st.markdown("### 🤖 Kích hoạt AI CIO")
        cio_provider = st.selectbox(
            "Chọn Model AI:",
            options=list(AI_PROVIDER_MAP.keys()),
            format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
            index=0,
            key="cio_ai_provider",
        )
        cio_key = st.text_input("Nhập API Key:", type="password", key="cio_api_key")
        
        # Kiểm tra cache trước
        from shared.ai_cio import _read_cache as _cio_read_cache
        _cached_sum = _cio_read_cache("executive_summary", cio_provider)
        
        col_run, col_refresh = st.columns([1, 1])
        with col_run:
            run_btn = st.button("🚀 Bắt đầu Tổng hợp", use_container_width=True)
        with col_refresh:
            if _cached_sum:
                refresh_btn = st.button("🔄 Tạo lại (ghi đè cache)", use_container_width=True, type="secondary")
            else:
                refresh_btn = False
        
        if run_btn or refresh_btn:
            if not cio_key:
                st.error("Vui lòng nhập API Key!")
            else:
                with st.spinner("AI CIO đang tổng hợp 7 báo cáo và đưa ra quyết định... (Quá trình có thể mất 1-2 phút)"):
                    try:
                        from shared.ai_cio import run_executive_summary, _read_cache
                        from shared.github_sync import upload_file
                        import os as _os
                        
                        # Nếu bấm "Tạo lại" hoặc force_refresh → xóa cache hiện tại
                        if refresh_btn:
                            cache_file = DATA_LAKE / "daily_cache" / f"executive_summary_{cio_provider}_{TODAY_STR}.txt"
                            if cache_file.exists():
                                _os.remove(cache_file)
                                st.info("🗑️ Đã xóa cache cũ, đang tạo báo cáo mới...")
                        
                        # Chạy (sẽ dùng cache nếu còn, hoặc gọi API nếu đã xóa)
                        cached_sum = _read_cache("executive_summary", cio_provider)
                        if cached_sum and not refresh_btn:
                            st.session_state["cio_report"] = cached_sum
                            st.session_state["cio_provider"] = cio_provider
                            st.success("Tải kết quả AI CIO từ bộ nhớ tạm!")
                            st.markdown(cached_sum)
                            report_text = cached_sum
                        else:
                            summary_report = run_executive_summary(cio_key, cio_provider)
                            st.session_state["cio_report"] = summary_report
                            st.session_state["cio_provider"] = cio_provider
                            st.success("Hoàn thành Báo cáo Tổng lệnh!")
                            st.markdown(summary_report)
                            report_text = summary_report
                        
                        # ── Đồng bộ lên GitHub (cả cache & mới tạo) ──
                        try:
                            cache_path = f"data_lake/daily_cache/executive_summary_{cio_provider}_{TODAY_STR}.txt"
                            upload_file(
                                cache_path,
                                report_text.encode("utf-8"),
                                f"Auto: AI CIO {cio_provider} report {TODAY_STR}",
                            )
                            st.success("✅ Đã đồng bộ báo cáo lên GitHub!")
                        except Exception as gh_err:
                            st.warning(f"⚠️ Chưa đồng bộ GitHub: {gh_err}")
                    except Exception as e:
                        st.error(f"Lỗi khi chạy AI CIO: {e}")
