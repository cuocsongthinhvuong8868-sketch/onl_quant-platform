"""
app.py — Trang chủ Quant Platform.
Điều hướng đến 3 nhánh chính: Macro Analysis, Micro Analysis, Behavioral Finance.
"""
import os
import streamlit as st
from pathlib import Path
# ── Wrap import để tránh crash khi chạy trên Streamlit Cloud ──
try:
    from shared.page_layout import setup_page
    setup_page("Quant Platform — Trang chủ")
except Exception as _layout_err:
    import streamlit as st
    st.set_page_config(page_title="Quant Platform", layout="wide", initial_sidebar_state="expanded")

# ── Đọc GitHub token từ Streamlit Secrets hoặc env ──
_github_token = os.getenv("GITHUB_TOKEN", "")
if not _github_token:
    try:
        _github_token = st.secrets["GITHUB_TOKEN"]
        os.environ["GITHUB_TOKEN"] = _github_token
    except Exception:
        _github_token = ""

# ── Helper: giải mã shortcut API Key từ Streamlit Secrets ──
from shared.api_key_helper import resolve_api_key as _resolve_api_key

# ── Header ──
st.title("📊 Quant Platform")
st.markdown(
    "Nền tảng phân tích định lượng đa chiều — **3 nhánh phân tích** chuyên sâu.  \n"
    "Nếu Người Dùng Muốn Sử Dụng AI Đọc Kết Quả, Vui Lòng Tích Hợp API của Mô Hình Kimmi AI Hoặc Deepseek AI."
)

# ── Navigation Cards ──
st.markdown("## 🚀 Chọn Nhánh Phân Tích")
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    with st.container(border=True, height=280):
        st.markdown("### 📈 Phân tích Vĩ mô")
        st.markdown("**Macro Analysis**")
        st.markdown(
            "- Thanh khoản, lãi suất & điều kiện tài chính\n"
            "- Regime từ định giá ngân hàng\n"
        )
        if st.button("📈 Vào Macro Analysis", key="btn_macro", use_container_width=True):

            st.switch_page("pages/A_Macro_Analysis.py")

with col2:
    with st.container(border=True, height=280):
        st.markdown("### 🔬 Phân tích Vi mô")
        st.markdown("**Micro Analysis**")
        st.markdown(
            "- Pairs Trading & Factor Examination\n"
            "- Tăng trưởng điều chỉnh rủi ro ngành ngân hàng\n"
            "- Quan hệ giá, yếu tố và định giá vi mô\n"
        )
        if st.button("🔬 Vào Micro Analysis", key="btn_micro", use_container_width=True):

            st.switch_page("pages/B_Micro_Analysis.py")

with col3:
    with st.container(border=True, height=280):
        st.markdown("### 🧠 Tài chính Hành vi")
        st.markdown("**Behavioral Finance**")
        st.markdown(
            "- Fear & Greed\n"
            "- Market Breadth / Dispersion\n"
            "- & nhiều hơn nữa..."
        )
        if st.button("🧠 Vào Behavioral Finance", key="btn_bf", use_container_width=True):
            st.switch_page("pages/C_Behavioral_Finance.py")

with col4:
    with st.container(border=True, height=280):
        st.markdown("### Data Management")
        st.markdown("**Model D - Data Health**")
        st.markdown(
            "- Raw and processed freshness\n"
            "- Missing-date detection\n"
            "- JSON / CSV health report"
        )
        if st.button("Open Data Health", key="btn_data_health", use_container_width=True):
            st.switch_page("pages/D_Data_Health.py")

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
        "kimi-2.6-local": {
            "display": "Kimi 2.6 Local",
            "api_model": "kimi-k2.6",
            "base_url": os.getenv("KIMI_LOCAL_BASE_URL", "http://127.0.0.1:5001/v1"),
            "temperature": 0.4,
            "timeout": 600,
        },
        "chatgpt-local": {
            "display": "ChatGPT Local",
            "api_model": "gpt-5.5",
            "base_url": "http://127.0.0.1:5003/v1",
            "temperature": 0.2,
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-v4-pro",
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
    st.info("ℹ️ Chưa có report AI CIO hôm nay. Chạy '🔥 Executive Summary (AI CIO)' để tạo; hoặc chọn ngày gần nhất muốn xem ở mục '📄 Xuất PDF Report AI CIO'.")

st.markdown("---")

# ── History Score & Regime ──
try:
    from pages.tools_page_C.history_score_regime import render as render_history
    render_history()
except Exception as e:
    st.error(f"❌ Lỗi tải Lịch sử Score & Regime: {e}")

st.markdown("---")

# ── Debug GitHub Sync ──
with st.expander("🔧 Kiểm tra & Đồng bộ GitHub"):
    try:
        from shared.github_sync import test_connection, upload_file
        import glob as _glob
        
        gh_test = test_connection()
        if gh_test["ok"]:
            st.success(f"✅ GitHub OK — User: {gh_test['user']} | Repo: {gh_test['repo']} | Push: {gh_test['can_push']}")
        else:
            st.error(f"❌ GitHub lỗi: {gh_test['error']}")
        
        st.markdown("---")
        st.markdown("#### 📤 Đồng bộ cache lên GitHub")
        st.caption("Đẩy toàn bộ file cache AI (executive_summary + các tool) lên GitHub. Chỉ bấm khi cần — tránh reload app không mong muốn.")
        
        _sync_provider = st.selectbox(
            "Chọn model AI để đồng bộ:",
            options=list(AI_PROVIDER_MAP.keys()),
            format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
            key="gh_sync_provider",
        )
        
        if st.button("📤 Đồng bộ cache lên GitHub", use_container_width=True, type="secondary"):
            if not _github_token:
                st.error("❌ Chưa có GITHUB_TOKEN trong Secrets. Vui lòng cấu hình trong Streamlit Cloud Dashboard → Secrets.")
            else:
                with st.spinner(f"⏳ Đang đồng bộ cache {AI_PROVIDER_MAP[_sync_provider]['display']} lên GitHub..."):
                    try:
                        _cache_dir = DATA_LAKE / "daily_cache"
                        _sync_files = list(_cache_dir.glob(f"*{_sync_provider}*.txt"))
                        _sync_files += list(_cache_dir.glob(f"executive_summary_{_sync_provider}_*.txt"))
                        # Deduplicate
                        _sync_files = list(set(_sync_files))
                        
                        if not _sync_files:
                            st.warning(f"⚠️ Không tìm thấy file cache nào cho {AI_PROVIDER_MAP[_sync_provider]['display']}.")
                        else:
                            _success = 0
                            _fail_msgs = []
                            _progress = st.progress(0)
                            for i, _fp in enumerate(_sync_files):
                                try:
                                    try:
                                        _rel_path = str(_fp.relative_to(ROOT_DIR)).replace("\\", "/")
                                    except ValueError:
                                        _rel_path = f"data_lake/daily_cache/{_fp.name}"
                                    _content = _fp.read_bytes()
                                    upload_file(
                                        _rel_path,
                                        _content,
                                        f"Sync: {_fp.name}",
                                    )
                                    _success += 1
                                except Exception as _fe:
                                    _fail_msgs.append(f"`{_fp.name}`: {_fe}")
                                _progress.progress((i + 1) / len(_sync_files))

                            if not _fail_msgs:
                                st.success(f"✅ Đã đồng bộ {_success} file lên GitHub thành công!")
                            else:
                                st.warning(f"⚠️ Đã đồng bộ {_success}/{len(_sync_files)} file. Lỗi:")
                                for _em in _fail_msgs:
                                    st.error(_em)
                    except Exception as _sync_err:
                        st.error(f"❌ Lỗi đồng bộ: {_sync_err}")
    except Exception as gh_debug_err:
        st.error(f"❌ Không kiểm tra được GitHub: {gh_debug_err}")

# ── Import PDF generator ──
from shared.pdf_export import create_ai_cio_pdf


def _normalize_cio_report_text(text: str) -> str:
    try:
        from shared.ai_cio import strip_wrapping_markdown_fence
    except Exception:
        return str(text or "")
    return strip_wrapping_markdown_fence(text)

# ── Xuất PDF AI CIO (chọn ngày) ──
if "cio_pdf_choice" not in st.session_state:
    st.session_state.cio_pdf_choice = None

col1, col2 = st.columns([1, 1])
with col1:
    with st.container(border=True):
        st.markdown("### 📄 Xuất PDF Report AI CIO")
        
        # Quét tất cả cache executive_summary trong daily_cache, chỉ lấy 10 cache gần nhất
        _all_cio_cache = list(DATA_LAKE.glob("daily_cache/executive_summary_*.txt"))
        
        # Sort by date extracted from filename (ddmmyy) instead of mtime
        # to ensure correct chronological order regardless of file timestamps
        def _extract_date_from_path(p):
            try:
                # Filename format: executive_summary_{provider}_{ddmmyy}.txt
                fname = p.stem  # e.g., "executive_summary_deepseek-v4-pro_040626"
                date_str = fname.split("_")[-1]  # e.g., "040626"
                return datetime.strptime(date_str, "%d%m%y")
            except Exception:
                return datetime.min
        
        _all_cio_cache = sorted(
            _all_cio_cache,
            key=_extract_date_from_path,
            reverse=True,
        )
        _all_cio_cache = _all_cio_cache[:10]  # 🔥 Chỉ lấy 10 ngày gần nhất
        
        if not _all_cio_cache:
            st.info("ℹ️ Chưa có report AI CIO hôm nay. Chạy '🔥 Executive Summary (AI CIO)' để tạo; hoặc chọn ngày gần nhất muốn xem ở report AI CIO.")
        else:
            # Gom nhóm theo ngày + provider
            _cio_options = {}
            for _fp in _all_cio_cache:
                _fname = _fp.name  # executive_summary_{provider}_{ddmmyy}.txt
                _parts = _fname.replace(".txt", "").split("_")
                # _parts = ['executive', 'summary', 'kimi-2.6', '110526']
                # hoặc ['executive', 'summary', 'deepseek', 'v4', 'pro', '110526']
                if len(_parts) >= 4:
                    _date_str = _parts[-1]  # ddmmyy
                    _provider_parts = _parts[2:-1]
                    _provider = "_".join(_provider_parts)
                    _date_display = f"{_date_str[:2]}/{_date_str[2:4]}/{_date_str[4:]}"
                    _provider_display = AI_PROVIDER_MAP.get(_provider, {}).get("display", _provider)
                    _label = f"{_date_display} — {_provider_display}"
                    _cio_options[_label] = {
                        "path": _fp,
                        "provider": _provider,
                        "date_str": _date_str,
                    }
            
            if _cio_options:
                # Sắp xếp theo ngày giảm dần (mới nhất lên đầu)
                def _parse_date_key(label):
                    try:
                        ds = _cio_options[label]["date_str"]
                        return datetime.strptime(ds, "%d%m%y")
                    except Exception:
                        return datetime.min
                _sorted_keys = sorted(_cio_options.keys(), key=_parse_date_key, reverse=True)

                # Reset session state nếu giá trị cũ không còn hợp lệ
                _prev = st.session_state.get("cio_pdf_date_selector")
                if _prev and _prev not in _sorted_keys:
                    st.session_state.cio_pdf_date_selector = _sorted_keys[0]

                _selected_label = st.selectbox(
                    "📅 Chọn ngày và model:",
                    options=_sorted_keys,
                    index=0,
                    key="cio_pdf_date_selector",
                )
                _sel = _cio_options[_selected_label]
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("⬇️ Tạo & Tải PDF", use_container_width=True, type="primary"):
                        st.session_state.cio_pdf_choice = _sel["provider"]
                        st.session_state.cio_pdf_date_str = _sel["date_str"]
                        st.session_state.cio_pdf_path = _sel["path"]
                with col_btn2:
                    if st.button("👁️ Xem trực tiếp TXT", use_container_width=True):
                        st.session_state.cio_txt_view = _sel["path"]
            else:
                st.info("ℹ️ Chưa có report AI CIO hôm nay. Chạy '🔥 Executive Summary (AI CIO)' để tạo; hoặc chọn ngày gần nhất muốn xem ở report AI CIO.")

# Xử lý tạo PDF sau khi chọn
if st.session_state.cio_pdf_choice and st.session_state.cio_pdf_choice != "__choose__":
    cio_provider = st.session_state.cio_pdf_choice
    _pdf_date_str = st.session_state.get("cio_pdf_date_str", TODAY_STR)
    _pdf_path_obj = st.session_state.get("cio_pdf_path", None)
    
    # Đọc report text
    report_text = ""
    if _pdf_path_obj and _pdf_path_obj.exists():
        report_text = _pdf_path_obj.read_text(encoding="utf-8")
        report_text = _normalize_cio_report_text(report_text)
    
    if not report_text:
        st.error(f"⚠️ Không tìm thấy báo cáo cho ngày {_pdf_date_str[:2]}/{_pdf_date_str[2:4]}/{_pdf_date_str[4:]}. Vui lòng chạy Executive Summary cho ngày này trước.")
        st.session_state.cio_pdf_choice = None
    else:
        with st.spinner("Đang tạo PDF..."):
            try:
                reports_dir = Path(__file__).resolve().parent / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                provider_prefix = cio_provider.replace("-", "_")
                pdf_path = reports_dir / f"{_pdf_date_str}_{provider_prefix}_executive_summary.pdf"
                create_ai_cio_pdf(
                    report_text,
                    pdf_path,
                    report_date=_pdf_date_str,
                    provider_key=cio_provider,
                )
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

# Xử lý hiển thị txt
if st.session_state.get("cio_txt_view"):
    _txt_path = st.session_state.cio_txt_view
    if _txt_path and _txt_path.exists():
        with st.expander("👁️ Nội dung Báo cáo TXT", expanded=True):
            st.markdown(_normalize_cio_report_text(_txt_path.read_text(encoding="utf-8")))
            if st.button("✖️ Đóng", key="btn_close_txt"):
                st.session_state.cio_txt_view = None
                st.rerun()

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
        cio_key_raw = st.text_input("Nhập API Key (hoặc shortcut 4 số):", type="password", key="cio_api_key",
            help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
        cio_key, cio_key_msg, cio_key_err = _resolve_api_key(cio_key_raw, cio_provider) if cio_key_raw else ("", "", False)
        if cio_key_err:
            st.error(cio_key_msg)
        elif cio_key_msg:
            st.success(cio_key_msg)
        
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
                        _client = OpenAI(api_key=cio_key.strip(), base_url=_cfg["base_url"], timeout=_cfg.get("timeout", 180))
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
                        _client = OpenAI(api_key=cio_key.strip(), base_url=_cfg["base_url"], timeout=_cfg.get("timeout", 180))
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
                
                with st.spinner("AI CIO đang tổng hợp macro, VN100 Corporate Health và 11 báo cáo định lượng/news... (Quá trình có thể mất 1-2 phút)"):
                    try:
                        from shared.ai_cio import run_executive_summary, _read_cache, _clear_all_tool_caches
                        import os as _os
                        
                        if refresh_btn:
                            # Xoá toàn bộ cache của 9 tool con + executive_summary trước khi chạy
                            _clear_all_tool_caches(cio_provider)
                            st.info("🗑️ Đã xóa cache cũ của các báo cáo con và executive_summary, đang tạo mới từ đầu. VN100 sẽ được đọc từ snapshot output hiện tại.")
                        
                        cached_sum = _read_cache("executive_summary", cio_provider)
                        if cached_sum and not refresh_btn:
                            cached_sum = _normalize_cio_report_text(cached_sum)
                            st.session_state["cio_report"] = cached_sum
                            st.session_state["cio_provider"] = cio_provider
                            st.success("Tải kết quả AI CIO từ bộ nhớ tạm!")
                            st.markdown(cached_sum)
                            report_text = cached_sum
                        else:
                            summary_report = run_executive_summary(cio_key, cio_provider)
                            summary_report = _normalize_cio_report_text(summary_report)
                            st.session_state["cio_report"] = summary_report
                            st.session_state["cio_provider"] = cio_provider
                            st.success("Hoàn thành Báo cáo Tổng lệnh!")
                            st.markdown(summary_report)
                            report_text = summary_report
                    except Exception as e:
                        st.error(f"Lỗi khi chạy AI CIO: {e}")

st.markdown("---")

# ── About this platform (Methodology summary) ──
_about_path = ROOT_DIR / "docs" / "about_this_platform.md"
with st.expander("📖 About this platform (Tóm tắt Methodology)", expanded=False):
    try:
        _about_text = _about_path.read_text(encoding="utf-8")
        st.markdown(_about_text)
        st.download_button(
            label="⬇️ Tải tóm tắt Methodology (.md)",
            data=_about_text.encode("utf-8"),
            file_name="about_this_platform.md",
            mime="text/markdown",
            use_container_width=True,
            type="secondary",
        )
    except FileNotFoundError:
        st.warning("Chưa tìm thấy `docs/about_this_platform.md` trong repository.")
    except Exception as e:
        st.warning(f"Không thể đọc tóm tắt methodology: {e}")

st.caption("© Quant Platform — 3 nhánh phân tích: Macro Analysis • Micro Analysis • Behavioral Finance")
