"""
pages/3_Behavioral_Finance.py — Nhánh Phân tích Tài chính Hành vi (Behavioral Finance).
Gộp tất cả 9 công cụ hiện tại vào một giao diện thống nhất.
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
        "id": "upside_ratio",
        "name": "🧬 Upside/Downside Ratio",
        "desc": "Hybrid MC Bidirectional Breadth Model — Phân tích Cung-Cầu với Monte Carlo ensemble",
        "page_module": "tools.upside_ratio.page",
        "render_func": "render",
    },
    {
        "id": "risk_adjusted_growth",
        "name": "📊 Risk-Adjusted Growth",
        "desc": "Phân tích tăng trưởng điều chỉnh rủi ro — DCF, P/B, Cash Payout cho ngân hàng",
        "page_module": "tools.risk_adjusted_growth.page",
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
    st.subheader("📋 Danh mục Công cụ")
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
    st.caption("© Quant Platform — Behavioral Finance • 9 công cụ phân tích")

# ── Đã chọn tool → Render tool tương ứng ───────────────────────────
else:
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
