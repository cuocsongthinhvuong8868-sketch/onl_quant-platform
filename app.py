"""
app.py — Trang chủ Quant Platform.
Điều hướng đến 3 nhánh chính: Macro Analysis, Micro Analysis, Behavioral Finance.
"""
import os
import streamlit as st
from pathlib import Path
from shared.page_layout import setup_page

setup_page("Quant Platform — Trang chủ")

# ── Đọc GitHub token từ Streamlit Secrets hoặc env ──
_github_token = os.getenv("GITHUB_TOKEN", "")
if not _github_token:
    try:
        _github_token = st.secrets["GITHUB_TOKEN"]
        os.environ["GITHUB_TOKEN"] = _github_token
    except Exception:
        _github_token = ""

# ── Header ──
st.title("📊 Quant Platform")
st.markdown(
    "Nền tảng phân tích định lượng đa chiều — **3 nhánh phân tích** chuyên sâu.  \n"
    "Nếu Người Dùng Muốn Sử Dụng AI Đọc Kết Quả, Vui Lòng Tích Hợp API của Mô Hình Kimmi AI Hoặc Deepseek AI."
)

# ── Navigation Cards ──
st.markdown("## 🚀 Chọn Nhánh Phân Tích")
st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    with st.container(border=True, height=280):
        st.markdown("### 📈 Phân tích Vĩ mô")
        st.markdown("**Macro Analysis**")
        st.markdown(
            "- Lãi suất & Chính sách tiền tệ\n"
            "- Tỷ giá & Dự trữ ngoại hối\n"
            "- Tăng trưởng GDP & CPI\n"
            "- Kinh tế toàn cầu"
        )
        st.markdown("🚧 **Đang phát triển**")
        if st.button("📈 Vào Macro Analysis", key="btn_macro", use_container_width=True):

            st.switch_page("pages/A_Macro_Analysis.py")

with col2:
    with st.container(border=True, height=280):
        st.markdown("### 🔬 Phân tích Vi mô")
        st.markdown("**Micro Analysis**")
        st.markdown(
            "- Báo cáo tài chính doanh nghiệp\n"
            "- Mô hình định giá DCF\n"
            "- Phân tích kỹ thuật cá nhân\n"
            "- Screening cổ phiếu"
        )
        st.markdown("🚧 **Đang phát triển**")
        if st.button("🔬 Vào Micro Analysis", key="btn_micro", use_container_width=True):

            st.switch_page("pages/B_Micro_Analysis.py")

with col3:
    with st.container(border=True, height=280):
        st.markdown("### 🧠 Tài chính Hành vi")
        st.markdown("**Behavioral Finance**")
        st.markdown(
            "✅ **9 công cụ sẵn sàng:**\n"
            "- Fear & Greed\n"
            "- Market Breadth / Dispersion\n"
            "- VaRES / Var-CVaR\n"
            "- ESR Monitor\n"
            "- & nhiều hơn nữa..."
        )
        if st.button("🧠 Vào Behavioral Finance", key="btn_bf", use_container_width=True):
            st.switch_page("pages/C_Behavioral_Finance.py")

st.markdown("---")

# ── Data lake status ──
from config import MARKET_DATA, DATA_LAKE, ROOT_DIR
from datetime import datetime, date

if MARKET_DATA.exists():
    mod = datetime.fromtimestamp(MARKET_DATA.stat().st_mtime)
    st.success(f"✅ Data lake sẵn sàng — cập nhật lần cuối: {mod.strftime('%d/%m/%Y %H:%M')}")
else:
    st.warning("⚠️ Data lake chưa có dữ liệu. Chạy `python update_data.py` trước.")

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

# ── AI CIO Report status ──
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

# ── Debug GitHub Sync ──
with st.expander("🔧 Kiểm tra GitHub Sync"):
    try:
        from shared.github_sync import test_connection
        gh_test = test_connection()
        if gh_test["ok"]:
            st.success(f"✅ GitHub OK — User: {gh_test['user']} | Repo: {gh_test['repo']} | Push: {gh_test['can_push']}")
        else:
            st.error(f"❌ GitHub lỗi: {gh_test['error']}")
    except Exception as gh_debug_err:
        st.error(f"❌ Không kiểm tra được GitHub: {gh_debug_err}")

# ── Import PDF generator ──
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
    
    text_width = int(pdf.w - 20)
    
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(10, 10)
    pdf.cell(text_width, 10, f"Executive Summary Report — {date.today().strftime('%d/%m/%Y')}", border=0, ln=1, align="C")
    pdf.ln(5)
    
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

# ── Xuất PDF AI CIO ──
if "cio_pdf_choice" not in st.session_state:
    st.session_state.cio_pdf_choice = None

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("📄 Xuất PDF Report AI CIO", type="primary", use_container_width=True):
        if len(_available_cio) == 1:
            st.session_state.cio_pdf_choice = _available_cio[0][0]
        elif len(_available_cio) > 1:
            st.session_state.cio_pdf_choice = "__choose__"
        else:
            st.session_state.cio_pdf_choice = None
            st.error("⚠️ Chưa có báo cáo AI CIO. Vui lòng chạy 'Executive Summary (AI CIO)' trước.")

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

if st.session_state.cio_pdf_choice and st.session_state.cio_pdf_choice != "__choose__":
    cio_provider = st.session_state.cio_pdf_choice
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
        
        # ── Nút kiểm tra API Key ──
        _test_btn = st.button("🔑 Kiểm tra API Key", use_container_width=True, type="secondary")
        if _test_btn:
            if not cio_key:
                st.error("⚠️ Vui lòng nhập API Key trước!")
            else:
                with st.spinner(f"⏳ Đang kiểm tra API Key {AI_PROVIDER_MAP[cio_provider]['display']}..."):
                    try:
                        from openai import OpenAI
                        _cfg = AI_PROVIDER_MAP[cio_provider]
                        _client = OpenAI(api_key=cio_key.strip(), base_url=_cfg["base_url"])
                        _resp = _client.chat.completions.create(
                            model=_cfg["api_model"],
                            messages=[{"role": "user", "content": "Hello"}],
                            max_tokens=5
                        )
                        st.success(f"✅ API Key hợp lệ! Model: {_cfg['api_model']} — Phản hồi: {_resp.choices[0].message.content}")
                    except Exception as _test_err:
                        _err_str = str(_test_err)
                        if "401" in _err_str or "Invalid Authentication" in _err_str:
                            st.error(f"❌ API Key không hợp lệ! Vui lòng kiểm tra lại key của {AI_PROVIDER_MAP[cio_provider]['display']}.")
                            st.info("💡 Mẹo: Key Kimi có dạng 'sk-...' (thường bắt đầu bằng 'sk-'). Hãy copy chính xác từ https://platform.moonshot.cn")
                        elif "402" in _err_str or "insufficient_quota" in _err_str:
                            st.error("❌ API Key đã hết hạn mức sử dụng (quota). Vui lòng nạp thêm hoặc dùng key khác.")
                        elif "429" in _err_str or "Rate limit" in _err_str:
                            st.error("⏳ Bị giới hạn tốc độ (Rate Limit). Vui lòng đợi 1-2 phút rồi thử lại.")
                        elif "Connection" in _err_str or "timeout" in _err_str:
                            st.error(f"🌐 Lỗi kết nối đến {AI_PROVIDER_MAP[cio_provider]['display']}. Kiểm tra internet hoặc base_url.")
                        else:
                            st.error(f"❌ Lỗi không xác định: {_test_err}")
        
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
                st.error("⚠️ Vui lòng nhập API Key!")
            else:
                # ── Kiểm tra API Key trước khi chạy toàn bộ pipeline ──
                with st.spinner(f"⏳ Đang xác thực API Key {AI_PROVIDER_MAP[cio_provider]['display']}..."):
                    try:
                        from openai import OpenAI
                        _cfg = AI_PROVIDER_MAP[cio_provider]
                        _client = OpenAI(api_key=cio_key.strip(), base_url=_cfg["base_url"])
                        _client.chat.completions.create(
                            model=_cfg["api_model"],
                            messages=[{"role": "user", "content": "Hi"}],
                            max_tokens=5
                        )
                    except Exception as _auth_e:
                        _err_str = str(_auth_e)
                        if "401" in _err_str or "Invalid Authentication" in _err_str:
                            st.error(f"❌ API Key {AI_PROVIDER_MAP[cio_provider]['display']} không hợp lệ! Vui lòng kiểm tra lại key.")
                            st.info("💡 Vào https://platform.moonshot.cn để lấy API Key Kimi hợp lệ.")
                        elif "402" in _err_str or "insufficient_quota" in _err_str:
                            st.error(f"❌ API Key đã hết quota! Vui lòng nạp thêm hoặc dùng key khác.")
                        else:
                            st.error(f"❌ Lỗi kết nối API: {_auth_e}")
                        st.stop()
                
                with st.spinner("AI CIO đang tổng hợp 9 báo cáo và đưa ra quyết định... (Quá trình có thể mất 1-2 phút)"):
                    try:
                        from shared.ai_cio import run_executive_summary, _read_cache
                        from shared.github_sync import upload_file
                        import os as _os
                        
                        if refresh_btn:
                            # Xoá toàn bộ cache của 9 tool con + executive_summary trước khi chạy
                            from shared.ai_cio import _clear_all_tool_caches
                            _clear_all_tool_caches(cio_provider)
                            st.info("🗑️ Đã xóa toàn bộ cache cũ của 9 công cụ con, đang tạo mới hoàn toàn từ đầu...")
                        
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
                        
                        try:
                            cache_path = f"data_lake/daily_cache/executive_summary_{cio_provider}_{TODAY_STR}.txt"
                            gh_result = upload_file(
                                cache_path,
                                report_text.encode("utf-8"),
                                f"Auto: AI CIO {cio_provider} report {TODAY_STR}",
                            )
                            st.success("✅ Đã đồng bộ báo cáo lên GitHub!")
                            if gh_result.get("file_url"):
                                st.markdown(f"🔗 [Xem file trên GitHub]({gh_result['file_url']})")
                        except Exception as gh_err:
                            st.warning(f"⚠️ Chưa đồng bộ GitHub: {gh_err}")
                    except Exception as e:
                        st.error(f"Lỗi khi chạy AI CIO: {e}")

st.markdown("---")
st.caption("© Quant Platform — 3 nhánh phân tích: Macro Analysis • Micro Analysis • Behavioral Finance")
