"""
pages/3_Behavioral_Finance.py — Nhánh Phân tích Tài chính Hành vi (Behavioral Finance).
Gộp các công cụ hành vi và rủi ro thị trường vào một giao diện thống nhất.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from shared.page_layout import setup_page
from shared.tool_registry import get_tool, tools_for_branch

setup_page("Quant Platform — Behavioral Finance")

# ── Định nghĩa danh sách tools ─────────────────────────────────────
TOOLS = tools_for_branch("behavioral")
BACKTEST_TOOL = get_tool("backtest").to_page_dict()

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
        if st.button(BACKTEST_TOOL["name"], use_container_width=True, key="btn_backtest"):
            st.session_state.bf_selected_tool = BACKTEST_TOOL["id"]
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

    # ── Special: Backtest Strategy ──
    if st.session_state.bf_selected_tool == "backtest":
        col_back, col_title = st.columns([1, 6])
        with col_back:
            if st.button("🔙 Danh mục", use_container_width=True, key="btn_back_backtest"):
                st.session_state.bf_selected_tool = None
                st.rerun()
        with col_title:
            st.markdown(f"## {BACKTEST_TOOL['name']}")
        try:
            module = __import__(BACKTEST_TOOL["page_module"], fromlist=[BACKTEST_TOOL["render_func"]])
            render_fn = getattr(module, BACKTEST_TOOL["render_func"])
            render_fn()
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
