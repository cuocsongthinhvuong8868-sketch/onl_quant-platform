from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


sys.path.insert(0, str(Path(__file__).parent.parent))

from config import AI_PROVIDER_MAP
from shared.ai_cio_chat import DEFAULT_MAX_SOURCES, ProjectDataCatalog
from shared.ai_cio_data_agent import (
    DATA_AGENT_VERSION,
    ask_ai_cio_data_agent,
    available_provider_keys,
    is_cloud_runtime,
)
from shared.api_key_helper import resolve_api_key
from shared.page_layout import setup_page


setup_page("Quant Platform - AI CIO Chat")

CHAT_MESSAGES_KEY = "ai_cio_chat_messages"
HIDDEN_DIAGNOSTIC_TITLES = {
    "AI-CIO Tool Metrics",
    "Data Health",
    "Kết quả tìm dữ liệu",
}


@st.cache_resource(show_spinner=False)
def _get_catalog() -> ProjectDataCatalog:
    return ProjectDataCatalog()


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1_024:
        return f"{size_bytes} B"
    if size_bytes < 1_024 * 1_024:
        return f"{size_bytes / 1_024:.1f} KB"
    return f"{size_bytes / (1_024 * 1_024):.1f} MB"


def _render_sources(sources: list[dict[str, Any]] | tuple[Any, ...]) -> None:
    if not sources:
        st.caption("Không có nguồn dữ liệu được truy xuất.")
        return
    with st.expander(f"Nguồn dữ liệu đã dùng ({len(sources)})", expanded=False):
        for index, source in enumerate(sources, start=1):
            if isinstance(source, dict):
                path = str(source.get("relative_path") or "")
                modified_at = str(source.get("modified_at") or "")
                size_bytes = int(source.get("size_bytes") or 0)
                excerpt = str(source.get("excerpt") or "")
                readable = bool(source.get("readable", True))
            else:
                path = source.relative_path
                modified_at = source.modified_at
                size_bytes = source.size_bytes
                excerpt = source.excerpt
                readable = source.readable
            status = "đã đọc" if readable else "chỉ metadata"
            st.markdown(f"**{index}. `{path}`**")
            st.caption(f"{status} · {_format_size(size_bytes)} · modified UTC {modified_at}")
            if excerpt:
                st.code(excerpt[:3_000], language=None)


def _serialize_sources(sources: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": source.relative_path,
            "suffix": source.suffix,
            "size_bytes": source.size_bytes,
            "modified_at": source.modified_at,
            "score": source.score,
            "excerpt": source.excerpt,
            "readable": source.readable,
        }
        for source in sources
    ]


def _is_volume_series(column: str) -> bool:
    normalized = str(column).strip().lower().replace("_", " ")
    return any(
        term in normalized
        for term in ("volume", "khối lượng", "khoi luong", "turnover", "giá trị giao dịch")
    ) or normalized in {"vol", "gtgd"}


def _render_tool_traces(tool_traces: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
    if not tool_traces:
        return
    with st.expander(f"Agent audit trail ({len(tool_traces)} bước)", expanded=False):
        for index, trace in enumerate(tool_traces, start=1):
            status = "OK" if trace.get("ok", True) else "ERROR"
            st.markdown(f"**{index}. `{trace.get('tool', 'unknown')}` — {status}**")
            if trace.get("arguments"):
                st.json(trace["arguments"], expanded=False)
            if trace.get("sources"):
                st.caption("Nguồn: " + ", ".join(str(source) for source in trace["sources"]))
            if trace.get("reason"):
                st.caption("Lý do: " + str(trace["reason"]))
            if trace.get("error"):
                st.error(str(trace["error"]))


def _render_displays(displays: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
    for display in displays:
        rows = display.get("rows") or []
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        title = str(display.get("title") or "Dữ liệu từ agent")
        if title in HIDDEN_DIAGNOSTIC_TITLES or display.get("visibility") == "diagnostic":
            continue
        display_type = str(display.get("type") or "table")
        if display_type in {"line_chart", "bar_chart"}:
            x_column = str(display.get("x") or "")
            y_columns = [str(column) for column in display.get("y") or [] if str(column) in frame.columns]
            if x_column not in frame.columns or not y_columns:
                continue
            frame[x_column] = pd.to_datetime(frame[x_column], errors="coerce")
            frame = frame.dropna(subset=[x_column]).sort_values(x_column)
            if frame.empty:
                continue
            x_tick_format = str(display.get("x_tick_format") or "%d/%m/%Y")
            x_hover_format = str(display.get("x_hover_format") or "%d/%m/%Y")
            chart_specs = [(display_type, title, y_columns)]
            if display_type == "line_chart":
                volume_columns = [column for column in y_columns if _is_volume_series(column)]
                primary_columns = [column for column in y_columns if column not in volume_columns]
                if volume_columns and primary_columns:
                    subject = title.removeprefix("Diễn biến ").replace("_cache", "").strip()
                    if subject.lower() in {"vnindex", "vn30", "hnxindex"}:
                        subject = subject.upper()
                    chart_specs = [
                        ("line_chart", title, primary_columns),
                        ("bar_chart", f"Khối lượng {subject}", volume_columns),
                    ]
            for chart_type, chart_title, chart_columns in chart_specs:
                st.markdown(f"#### {chart_title}")
                if chart_type == "bar_chart":
                    figure = px.bar(frame, x=x_column, y=chart_columns, barmode="group")
                else:
                    figure = px.line(frame, x=x_column, y=chart_columns, markers=True)
                figure.update_layout(
                    legend_title_text=str(display.get("legend_title") or ""),
                    hovermode="x unified",
                    yaxis_title=(
                        "Khối lượng"
                        if chart_type == "bar_chart"
                        else str(display.get("y_axis_title") or "")
                    ),
                    margin={"l": 10, "r": 10, "t": 20, "b": 55},
                )
                figure.update_xaxes(
                    title_text=str(display.get("x_axis_title") or "Thời gian"),
                    type="date",
                    tickformat=x_tick_format,
                    hoverformat=x_hover_format,
                    showticklabels=True,
                    tickangle=-35 if len(frame) > 6 else 0,
                    nticks=min(max(len(frame), 2), 12),
                    automargin=True,
                    showgrid=True,
                )
                st.plotly_chart(figure, use_container_width=True)
        else:
            st.markdown(f"#### {title}")
            st.dataframe(frame, hide_index=True, use_container_width=True)
        if display.get("source"):
            st.caption(f"Nguồn hiển thị: `{display['source']}`")


def _plain_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": str(message.get("role") or ""), "content": str(message.get("content") or "")}
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and not message.get("error")
    ]


catalog = _get_catalog()
if CHAT_MESSAGES_KEY not in st.session_state:
    st.session_state[CHAT_MESSAGES_KEY] = []

st.title("Chat với AI CIO")
st.caption(
    f"AI-CIO Data Agent `{DATA_AGENT_VERSION}` dùng AI Query Planner trước khi đọc dữ liệu, "
    "sau đó gọi công cụ read-only và dựng bảng/biểu đồ từ nguồn."
)
st.info(
    "Quyền đọc gồm `data_lake/`, `reports/`, `docs/`, `config/`, `tickers.csv` và `tickers_400.csv`. "
    "Agent không có shell, không sửa file và không tự chạy updater; dữ liệu thiếu/cũ phải được báo `DATA INSUFFICIENT`."
)

with st.sidebar:
    st.header("Cấu hình AI CIO")
    provider_options = available_provider_keys()
    if not provider_options:
        st.error("Không có AI provider phù hợp với môi trường hiện tại.")
        st.stop()
    provider_key = st.selectbox(
        "Model AI",
        options=provider_options,
        format_func=lambda key: AI_PROVIDER_MAP[key]["display"],
        key="ai_cio_chat_provider",
    )
    if is_cloud_runtime():
        st.caption("Cloud mode: các provider localhost đã được ẩn.")
    raw_api_key = st.text_input(
        "API Key hoặc shortcut 4 số",
        type="password",
        key="ai_cio_chat_api_key",
    )
    api_key, key_message, key_error = (
        resolve_api_key(raw_api_key, provider_key) if raw_api_key else ("", "", False)
    )
    if key_error:
        st.error(key_message)
    elif key_message:
        st.success(key_message)
    st.caption("Excerpt từ nguồn được chọn sẽ được gửi tới AI provider này. Dùng provider local nếu dữ liệu nhạy cảm.")

    max_sources = st.slider(
        "Số nguồn agent tối đa",
        min_value=4,
        max_value=12,
        value=DEFAULT_MAX_SOURCES,
        step=1,
    )
    st.caption("Giới hạn nguồn cho compatibility router và retrieval dự phòng cuối cùng.")

    if st.button("Làm mới danh mục dữ liệu", use_container_width=True):
        with st.spinner("Đang lập lại danh mục..."):
            catalog.refresh()
        st.success("Đã làm mới danh mục dữ liệu.")

    stats = catalog.stats()
    st.metric("File trong catalog", stats["total_files"])
    st.caption(
        f"Đọc nội dung: {stats['readable_files']} · Chỉ metadata: {stats['metadata_only_files']} · "
        f"Dung lượng: {stats['total_size_mb']} MB"
    )
    st.caption(f"Làm mới UTC: {stats.get('refreshed_at') or 'N/A'}")

    if st.button("Xóa hội thoại", use_container_width=True, type="secondary"):
        st.session_state[CHAT_MESSAGES_KEY] = []
        st.rerun()

st.markdown("#### Câu hỏi gợi ý")
suggestion_columns = st.columns(4)
suggestions = (
    "Rủi ro hệ thống hiện tại là gì và tín hiệu nào đang chi phối?",
    "VNINDEX thay đổi thế nào trong 3 phiên gần nhất?",
    "Những công cụ nào đang cho tín hiệu mâu thuẫn nhau?",
    "Nguồn dữ liệu quan trọng nào đang cũ hoặc chưa đủ?",
)
pending_question = ""
for column, suggestion in zip(suggestion_columns, suggestions):
    with column:
        if st.button(suggestion, use_container_width=True):
            pending_question = suggestion

st.caption("Có thể gọi trực tiếp một file bằng cú pháp `@data_lake/vnindex_cache.csv` trong câu hỏi.")
st.markdown("---")

messages: list[dict[str, Any]] = st.session_state[CHAT_MESSAGES_KEY]
for message in messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            _render_tool_traces(message.get("tool_traces", []))
            _render_displays(message.get("displays", []))
            _render_sources(message.get("sources", []))

chat_question = st.chat_input("Hỏi AI CIO về thị trường, công cụ hoặc bất kỳ dữ liệu nào trong dự án...")
question = pending_question or chat_question or ""
if question:
    with st.chat_message("user"):
        st.markdown(question)

    history = _plain_history(messages)
    messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        if key_error:
            error_message = "API key shortcut không hợp lệ. Hãy kiểm tra lại cấu hình Secrets."
            st.error(error_message)
            messages.append({"role": "assistant", "content": error_message, "sources": [], "error": True})
        elif not api_key:
            error_message = "Hãy nhập API key hoặc shortcut ở thanh bên để bắt đầu chat."
            st.warning(error_message)
            messages.append({"role": "assistant", "content": error_message, "sources": [], "error": True})
        else:
            try:
                with st.spinner("AI CIO đang truy xuất dữ liệu và đối chiếu bằng chứng..."):
                    result = ask_ai_cio_data_agent(
                        api_key,
                        provider_key,
                        question,
                        history=history,
                        catalog=catalog,
                        max_sources=max_sources,
                    )
                serialized_sources = _serialize_sources(result.sources)
                st.markdown(result.answer)
                _render_tool_traces(result.tool_traces)
                _render_displays(result.displays)
                _render_sources(serialized_sources)
                st.caption(f"Execution mode: `{result.mode}` · `{result.methodology_version}`")
                messages.append(
                    {
                        "role": "assistant",
                        "content": result.answer,
                        "sources": serialized_sources,
                        "tool_traces": list(result.tool_traces),
                        "displays": list(result.displays),
                        "mode": result.mode,
                        "provider_key": result.provider_key,
                        "methodology_version": result.methodology_version,
                    }
                )
            except Exception as error:
                error_message = f"Không thể hoàn tất câu hỏi: {error}"
                st.error(error_message)
                messages.append({"role": "assistant", "content": error_message, "sources": [], "error": True})
