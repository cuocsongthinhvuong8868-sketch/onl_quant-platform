"""
pages/A_Macro_Analysis.py — Nhánh Phân tích Vĩ mô (Macro Analysis).
Grid menu các công cụ vĩ mô + gọi render() động.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page

setup_page("Quant Platform — Macro Analysis")

# ── Định nghĩa danh sách tools ─────────────────────────────────────
TOOLS = [
    {
        "id": "fed_liquidity",
        "name": "🏦 Fed Liquidity Monitor",
        "desc": "Net Liquidity (WALCL − TGA − RRP) + Impulse EMA + Z-Score 52W → Tín hiệu ADD/CUT/HOLD",
        "page_module": "tools.fed_liquidity.page",
        "render_func": "render",
    },
    {
        "id": "global_financial_conditions",
        "name": "🌐 Global Financial Conditions",
        "desc": "VIX + MOVE + HY OAS + CCC OAS · Static PCA composite · Regime via PC1 percentile rank 3Y (STRESS/ELEVATED/CALM)",
        "page_module": "tools.global_financial_conditions.page",
        "render_func": "render",
    },
    {
        "id": "humility_falsification",
        "name": "🧭 Humility & Falsification Monitor",
        "desc": "Đối chiếu điều kiện falsification trong AI CIO T-1 với dữ liệu T từ VNIBOR, Breadth, ESR, EVT, Coupling và Global Conditions",
        "page_module": "tools.humility_falsification.page",
        "render_func": "render",
    },
    {
        "id": "vnibor",
        "name": "🏦 VNIBOR Monitor",
        "desc": "Lãi suất qua đêm và các kỳ hạn ngắn liên ngân hàng · Phân loại trạng thái thanh khoản (Regime Percentile 1Y) · Tác động tới VN-Index",
        "page_module": "tools.vnibor.page",
        "render_func": "render",
    },
    {
        "id": "bank_valuation",
        "name": "🏦 Bank Valuation",
        "desc": "Định giá bottom-up nhóm ngân hàng: Adjusted Book Value, Sustainable ROE, Residual Income, stress fair P/B và regime từ valuation breadth.",
        "page_module": "tools.bank_valuation.page",
        "render_func": "render",
    },
    {
        "id": "ltmm",
        "name": "📊 Liquidity Transmission (LTMM)",
        "desc": "Theo dõi kênh truyền dẫn thanh khoản hệ thống: Thượng nguồn (upstream), Lớp ma sát (friction), và Hạ nguồn (market liquidity)",
        "page_module": "tools.ltmm.page",
        "render_func": "render",
    },
    {
        "id": "vn100_earnings_health",
        "name": "🇻🇳 VN100 Earnings Health",
        "desc": "Fundamental earnings monitor VN100: Momentum + Breadth + Stability 12Q + Profitability + CSAD blend + PCA validation",
        "page_module": "tools.vn100_earnings_health.page",
        "render_func": "render",
    },
]

# ── Khởi tạo session_state ─────────────────────────────────────────
if "macro_selected_tool" not in st.session_state:
    st.session_state.macro_selected_tool = None

# ── Header ──────────────────────────────────────────────────────────
st.title("📈 Phân tích Vĩ mô (Macro Analysis)")
st.markdown(
    "Khoang tàu **Macro Analysis** tập trung phân tích các yếu tố vĩ mô toàn cầu "
    "và Việt Nam có tác động tới định giá tài sản và tâm lý thị trường."
)

st.markdown("---")

# ── Nếu chưa chọn tool → Hiển thị Grid danh mục ────────────────────
if st.session_state.macro_selected_tool is None:
    st.subheader("📋 Danh mục Công cụ")
    st.markdown("Chọn một công cụ bên dưới để bắt đầu phân tích:")

    cols_per_row = 3
    for i in range(0, len(TOOLS), cols_per_row):
        row_tools = TOOLS[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, tool in zip(cols, row_tools):
            with col:
                with st.container(border=True, height=200):
                    st.markdown(f"### {tool['name']}")
                    st.caption(tool['desc'])
                    if st.button(
                        f"🔓 Mở {tool['name'].split('—')[0].strip()}",
                        key=f"btn_macro_{tool['id']}",
                        width="stretch",
                    ):
                        st.session_state.macro_selected_tool = tool['id']
                        st.rerun()

    st.markdown("---")
    st.info(
        "🚧 **Các công cụ đang phát triển thêm:**\n"
        "- 💱 Tỷ giá & Dự trữ ngoại hối — Đánh giá áp lực tỷ giá USD/VND\n"
        "- 📉 Tăng trưởng GDP & CPI — Tương quan vĩ mô và TTCK\n"
        "- 🛢️ Hàng hoá toàn cầu — Dầu, vàng, đồng",
        icon="ℹ️",
    )
    st.caption(f"© Quant Platform — Nhánh Macro Analysis • {len(TOOLS)} công cụ")

# ── Đã chọn tool → Render tool tương ứng ───────────────────────────
else:
    current_tool = None
    for t in TOOLS:
        if t["id"] == st.session_state.macro_selected_tool:
            current_tool = t
            break

    if current_tool is None:
        st.error("❌ Công cụ không tồn tại!")
        if st.button("🔙 Quay lại danh mục"):
            st.session_state.macro_selected_tool = None
            st.rerun()
        st.stop()

    col_back, col_title = st.columns([1, 6])
    with col_back:
        if st.button("🔙 Danh mục", width="stretch"):
            st.session_state.macro_selected_tool = None
            st.rerun()
    with col_title:
        st.markdown(f"## {current_tool['name']}")

    try:
        module = __import__(current_tool["page_module"], fromlist=[current_tool["render_func"]])
        render_fn = getattr(module, current_tool["render_func"])
        render_fn()
    except Exception as e:
        st.error(f"❌ Lỗi khi tải công cụ: {e}")
        st.exception(e)
        if st.button("🔙 Quay lại danh mục"):
            st.session_state.macro_selected_tool = None
            st.rerun()
