"""
pages/3_Behavioral_Finance.py — Nhánh Phân tích Tài chính Hành vi (Behavioral Finance).
Gộp các công cụ hành vi và rủi ro thị trường vào một giao diện thống nhất.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page

setup_page("Quant Platform — Behavioral Finance")

# ── Định nghĩa danh sách tools ─────────────────────────────────────
TOOLS = [
    {
        "id": "fear_greed",
        "name": "🎯 Market Sentiment (Fear & Greed)",
        "desc": "PCA & EGARCH — Đo lường tâm lý thị trường qua PCA, EGARCH(1,1,1) Skewed-T, Kelly Skewness",
        "page_module": "tools.fear_greed.page",
        "render_func": "render",
    },
    {
        "id": "sentiment_factor_news",
        "name": "📰 News Sentiment Factor",
        "desc": "Rule-based macro/news sentiment feed từ Mozyfin và WiData: composite, regime, channel scores và headline drivers.",
        "page_module": "tools.sentiment_factor_news.page",
        "render_func": "render",
    },
    {
        "id": "upside_ratio",
        "name": "🧬 Upside/Downside Ratio",
        "desc": "Hybrid MC Bidirectional Breadth Model — Phân tích Cung-Cầu với Monte Carlo ensemble",
        "page_module": "tools.upside_ratio.page",
        "render_func": "render",
    },
    {
        "id": "market_breadth",
        "name": "📈 Market Breadth",
        "desc": "Độ rộng thị trường — Số mã >MA20/60/125/252, Top 10 Volume Leaders",
        "page_module": "tools.market_breadth.page",
        "render_func": "render",
    },
    {
        "id": "esr_monitor",
        "name": "⚡ ESR Monitor",
        "desc": "Hệ thống Cảnh báo Rủi ro Hệ thống — PCA trên VN30, phát hiện SAFE/WARNING/CRITICAL",
        "page_module": "tools.esr_monitor.page",
        "render_func": "render",
    },
    {
        "id": "dispersion",
        "name": "🔄 Dispersion",
        "desc": "Phân tích phân tán thị trường — Volatility skew, term structure",
        "page_module": "tools.dispersion.page",
        "render_func": "render",
    },
    {
        "id": "va_res",
        "name": "🛡️ VaRES Engine",
        "desc": "3 Module: A-Single Ticker, B-VN30 Stress, C-Market Complacency với Self-Baseline",
        "page_module": "tools.va_res.page",
        "render_func": "show",
    },
    {
        "id": "manipulation",
        "name": "🔍 Manipulation Detection",
        "desc": "Phát hiện dấu hiệu thao túng giá — Các metrics đặc biệt về hành vi giao dịch",
        "page_module": "tools.manipulation.page",
        "render_func": "render",
    },
    {
        "id": "var_cvar_vnindex",
        "name": "📉 Var-CVaR VNINDEX",
        "desc": "Value-at-Risk & Expected Shortfall cho VNINDEX — Rolling σ, Parametric & Historical VaR, ES",
        "page_module": "tools.var_cvar_vnindex.page",
        "render_func": "show",
    },
]

# ── Khởi tạo session_state ─────────────────────────────────────────
if "bf_selected_tool" not in st.session_state:
    st.session_state.bf_selected_tool = None

# ── Header ──────────────────────────────────────────────────────────
st.title("🧠 Phân tích Tài chính Hành vi (Behavioral Finance)")
st.markdown(
    "Khoang tàu **Behavioral Finance** tập hợp tất cả công cụ phân tích "
    "hành vi thị trường, tâm lý nhà đầu tư và rủi ro hệ thống."
)

st.markdown("---")

# ── Nếu chưa chọn tool → Hiển thị Grid danh mục ────────────────────
if st.session_state.bf_selected_tool is None:
    col_title, col_history = st.columns([4, 2])
    with col_title:
        st.subheader("📋 Danh mục Công cụ")
    with col_history:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📊 History Score", use_container_width=True, key="btn_history_score"):
                st.session_state.bf_selected_tool = "history_score_regime"
                st.rerun()
        with c2:
            if st.button("⚖️ Backtest Strategy", use_container_width=True, key="btn_backtest"):
                st.session_state.bf_selected_tool = "backtest"
                st.rerun()
    st.markdown("Chọn một công cụ bên dưới để bắt đầu phân tích:")

    # Chia thành các hàng, mỗi hàng 3 cột
    cols_per_row = 3
    for i in range(0, len(TOOLS), cols_per_row):
        row_tools = TOOLS[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, tool in zip(cols, row_tools):
            with col:
                with st.container(border=True, height=200):
                    st.markdown(f"### {tool['name']}")
                    st.caption(tool['desc'])
                    if st.button(f"🔓 Mở {tool['name'].split('—')[0].strip()}", key=f"btn_{tool['id']}", use_container_width=True):
                        st.session_state.bf_selected_tool = tool['id']
                        st.rerun()

    st.markdown("---")
    st.caption(f"© Quant Platform — Behavioral Finance • {len(TOOLS)} công cụ phân tích")

# ── Đã chọn tool → Render tool tương ứng ───────────────────────────
else:
    # ── Special: History Score & Regime ──
    if st.session_state.bf_selected_tool == "history_score_regime":
        col_back, col_title = st.columns([1, 6])
        with col_back:
            if st.button("🔙 Danh mục", use_container_width=True, key="btn_back_history"):
                st.session_state.bf_selected_tool = None
                st.rerun()
        with col_title:
            st.markdown("## 📊 History Score & Regime")
        try:
            from pages.tools_page_C.history_score_regime import render as render_history
            render_history()
        except Exception as e:
            st.error(f"❌ Lỗi khi tải trang: {e}")
            st.exception(e)
        st.stop()

    # ── Special: Backtest Strategy ──
    if st.session_state.bf_selected_tool == "backtest":
        col_back, col_title = st.columns([1, 6])
        with col_back:
            if st.button("🔙 Danh mục", use_container_width=True, key="btn_back_backtest"):
                st.session_state.bf_selected_tool = None
                st.rerun()
        with col_title:
            st.markdown("## ⚖️ Backtest Strategy")
        try:
            from tools.backtest.page import show as render_backtest
            render_backtest()
        except Exception as e:
            st.error(f"❌ Lỗi khi tải trang Backtest: {e}")
            st.exception(e)
        st.stop()

    # Tìm tool trong danh sách
    current_tool = None
    for t in TOOLS:
        if t["id"] == st.session_state.bf_selected_tool:
            current_tool = t
            break

    if current_tool is None:
        st.error("❌ Công cụ không tồn tại!")
        if st.button("🔙 Quay lại danh mục"):
            st.session_state.bf_selected_tool = None
            st.rerun()
        st.stop()

    # ── Header + nút Back ──
    col_back, col_title = st.columns([1, 6])
    with col_back:
        if st.button("🔙 Danh mục", use_container_width=True):
            st.session_state.bf_selected_tool = None
            st.rerun()
    with col_title:
        st.markdown(f"## {current_tool['name']}")

    # ── Import và render tool ──
    try:
        module = __import__(current_tool["page_module"], fromlist=[current_tool["render_func"]])
        render_fn = getattr(module, current_tool["render_func"])
        render_fn()
    except Exception as e:
        st.error(f"❌ Lỗi khi tải công cụ: {e}")
        st.exception(e)
        if st.button("🔙 Quay lại danh mục"):
            st.session_state.bf_selected_tool = None
            st.rerun()
