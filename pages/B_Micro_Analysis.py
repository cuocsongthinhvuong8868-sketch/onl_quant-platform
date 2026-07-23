"""
pages/B_Micro_Analysis.py — Nhánh Phân tích Vi mô (Micro Analysis).
Grid menu các công cụ vi mô + gọi render() động (mirror A_Macro_Analysis pattern).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page
from shared.tool_registry import tools_for_branch

setup_page("Quant Platform — Micro Analysis")

# ── Định nghĩa danh sách tools ─────────────────────────────────────
TOOLS = tools_for_branch("micro")

# ── Khởi tạo session_state ─────────────────────────────────────────
if "micro_selected_tool" not in st.session_state:
    st.session_state.micro_selected_tool = None

# ── Header ──────────────────────────────────────────────────────────
st.title("🔬 Phân tích Vi mô (Micro Analysis)")
st.markdown(
    "Khoang tàu **Micro Analysis** tập trung phân tích cấu trúc từng mã/ngành, "
    "factor cross-section và các bài toán stat-arb trên cổ phiếu Việt Nam."
)

st.markdown("---")

# ── Nếu chưa chọn tool → Hiển thị Grid danh mục ────────────────────
if st.session_state.micro_selected_tool is None:
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
                        key=f"btn_micro_{tool['id']}",
                        use_container_width=True,
                    ):
                        st.session_state.micro_selected_tool = tool['id']
                        st.rerun()

    st.markdown("---")
    st.info(
        "🚧 **Các công cụ đang phát triển thêm:**\n"
        "- 📄 **Báo cáo tài chính doanh nghiệp** — Phân tích P/E, P/B, ROE\n"
        "- 📊 **DCF Valuation** — Chiết khấu dòng tiền\n"
        "- 🎯 **Stock screening** — Filter theo chỉ số fundamentals",
        icon="ℹ️",
    )
    st.caption(f"© Quant Platform — Nhánh Micro Analysis • {len(TOOLS)} công cụ")

# ── Đã chọn tool → Render tool tương ứng ───────────────────────────
else:
    current_tool = None
    for t in TOOLS:
        if t["id"] == st.session_state.micro_selected_tool:
            current_tool = t
            break

    if current_tool is None:
        st.error("❌ Công cụ không tồn tại!")
        if st.button("🔙 Quay lại danh mục"):
            st.session_state.micro_selected_tool = None
            st.rerun()
        st.stop()

    col_back, col_title = st.columns([1, 6])
    with col_back:
        if st.button("🔙 Danh mục", use_container_width=True):
            st.session_state.micro_selected_tool = None
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
            st.session_state.micro_selected_tool = None
            st.rerun()
