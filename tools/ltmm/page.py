"""Completely self-contained, integrated Streamlit UI for the Quant Platform's LTMM tool.

Displays Tool 1 (THM), Tool 2 (BND), and AI CIO using raw JSON/Markdown files
placed in data_lake/data_LTMM/sourse_raw/ and data_lake/data_LTMM/AI_CIO_raw/.
"""
from __future__ import annotations

import os
import json
import numpy as np
import pandas as pd
import datetime as dt
from pathlib import Path
from typing import Any
import streamlit as st

# Import global paths from config
from config import DATA_LAKE

RAW_DIR = DATA_LAKE / "data_LTMM" / "AI_CIO_raw"
SOURCE_DIR = DATA_LAKE / "data_LTMM" / "sourse_raw"

# Define index methodology notes internally for standalone completeness
INDEX_METHOD_NOTES = {
    "FLI": "FLI is computed as the normalized average of overnight, weekly, and monthly rates.",
    "FRI_banking": "FRI Banking reflects interbank rate spreads, required reserve spreads, and solvency indicators.",
    "FRI_collateral": "FRI Collateral measures government bond yield volatility and sovereign yield spreads.",
    "FRI_counterparty": "FRI Counterparty stress is modeled from interbank ON volume and rate percentiles.",
    "FRI_intermediary": "FRI Intermediary stress uses CASA QoQ velocity and JSCB-SOCB retail rate spreads.",
    "FRI_regulatory": "FRI Regulatory is a retail stress indicator driven by market circuit breakers.",
    "FRI_risk": "FRI Risk is a composite stress score of all sub-indices.",
    "MLI": "MLI represents equity market liquidity derived from VN30/VNIndex volume and turnover.",
}

# --- Core Helper Functions (100% Standalone) ---

def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
        }
        .ltmm-topbar {
            border: 1px solid #d6d9de;
            border-left: 6px solid #44546a;
            background: #f7f8fa;
            padding: 18px 20px;
            margin-bottom: 18px;
        }
        .ltmm-topbar h1 {
            margin: 0 0 4px 0;
            font-size: 1.65rem;
            letter-spacing: 0;
        }
        .ltmm-topbar p {
            margin: 0;
            color: #5b6470;
            font-size: 0.96rem;
        }
        .ltmm-card {
            border: 1px solid #d8dde3;
            background: #ffffff;
            padding: 14px 16px;
            min-height: 112px;
            border-radius: 6px;
            border-left-width: 6px;
        }
        .ltmm-card.neutral { border-left-color: #607d8b; }
        .ltmm-card.easy { border-left-color: #2e7d32; }
        .ltmm-card.watch { border-left-color: #b7791f; }
        .ltmm-card.stress { border-left-color: #b42318; }
        .ltmm-card.muted { border-left-color: #8a8f98; }
        .ltmm-card-title {
            font-size: 0.78rem;
            text-transform: uppercase;
            color: #59636f;
            font-weight: 700;
            letter-spacing: 0;
            margin-bottom: 8px;
        }
        .ltmm-card-value {
            font-size: 1.45rem;
            line-height: 1.2;
            color: #111827;
            font-weight: 760;
            letter-spacing: 0;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .ltmm-card-caption {
            margin-top: 8px;
            color: #5b6470;
            font-size: 0.86rem;
            line-height: 1.28;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .ltmm-section {
            font-size: 1.05rem;
            font-weight: 760;
            margin: 18px 0 8px 0;
            color: #1f2937;
        }
        .ltmm-pill {
            display: inline-flex;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            border: 1px solid #cbd5e1;
            color: #334155;
            background: #f8fafc;
            max-width: 100%;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .ltmm-pill.fire {
            color: #7f1d1d;
            background: #fef2f2;
            border-color: #fecaca;
        }
        .ltmm-pill.non-fire {
            color: #14532d;
            background: #f0fdf4;
            border-color: #bbf7d0;
        }
        div[data-testid="stSidebar"] {
            border-right: 1px solid #e5e7eb;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def _render_topbar(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="ltmm-topbar">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _number(value: Any, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "n/a"
    return f"{numeric:.{digits}f}"

def _state_class(state: str) -> str:
    normalized = str(state).lower().replace(" ", "-")
    if "alert" in normalized or "stress" in normalized:
        return "stress"
    if "tightening" in normalized or "warning" in normalized:
        return "watch"
    if "easy" in normalized or "high" in normalized:
        return "easy"
    if "weak" in normalized or "unavailable" in normalized:
        return "muted"
    return "neutral"

def _card_html(title: str, value: str, caption: str, state: str = "neutral") -> str:
    class_name = _state_class(state)
    return f"""
    <div class="ltmm-card {class_name}">
        <div class="ltmm-card-title">{title}</div>
        <div class="ltmm-card-value">{value}</div>
        <div class="ltmm-card-caption">{caption}</div>
    </div>
    """

def _index_row(latest: pd.DataFrame, index_name: str) -> pd.Series | None:
    if latest.empty or "index_name" not in latest:
        return None
    rows = latest.loc[latest["index_name"].eq(index_name)]
    if rows.empty:
        return None
    return rows.iloc[0]

def _metric_value(df: pd.DataFrame, index_name: str, column: str) -> str:
    row = _index_row(df, index_name)
    if row is None or column not in row:
        return "n/a"
    val = row[column]
    if pd.isna(val):
        return "n/a"
    return _number(val) if isinstance(val, (int, float)) else str(val)

def _summary_state(latest: pd.DataFrame, triggers: pd.DataFrame) -> str:
    fired = 0 if triggers.empty else int(triggers["signal_state"].eq("FIRE").sum())
    if fired:
        return "ALERT"
    mli = pd.to_numeric(
        latest.loc[latest["index_name"].eq("MLI"), "index_value"], errors="coerce"
    )
    fli = pd.to_numeric(
        latest.loc[latest["index_name"].eq("FLI"), "index_value"], errors="coerce"
    )
    mli_value = mli.iloc[0] if not mli.empty else pd.NA
    fli_value = fli.iloc[0] if not fli.empty else pd.NA
    if pd.notna(fli_value) and pd.notna(mli_value) and fli_value >= 0.75 and mli_value >= 0.75:
        return "FUNDING STRESS TRANSMITTING"
    if pd.notna(fli_value) and fli_value >= 0.75:
        return "UPSTREAM TIGHTENING"
    if pd.notna(mli_value) and mli_value >= 0.75:
        return "MARKET LIQUIDITY STRESS"
    return "MONITOR"

def df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "*Không có dữ liệu*"
    try:
        return df.to_markdown(index=False)
    except Exception:
        # Fallback manual formatting
        lines = []
        cols = list(df.columns)
        lines.append("| " + " | ".join(map(str, cols)) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for row in df.itertuples(index=False):
            row_str = []
            for val in row:
                s = str(val).replace("\n", " ").replace("|", "\\|")
                row_str.append(s)
            lines.append("| " + " | ".join(row_str) + " |")
        return "\n".join(lines)

def build_result_handout_text(data: dict[str, pd.DataFrame]) -> str:
    del data
    return "HANDOUT HƯỚNG DẪN ĐỌC KẾT QUẢ LTMM - BẢN ĐỒNG BỘ NỀN TẢNG\n\nXem chi tiết hướng dẫn tại file chính của hệ thống."

# --- Main Tool Renderers (100% Standalone) ---

def _render_tool1_thm(data: dict[str, pd.DataFrame]) -> None:
    latest = data.get("latest_indices", pd.DataFrame())
    triggers = data.get("triggers", pd.DataFrame())
    headline = _summary_state(latest, triggers)
    as_of = "n/a" if latest.empty else str(latest["as_of_date"].max())
    fired = 0 if triggers.empty else int(triggers["signal_state"].eq("FIRE").sum())
    excluded = 0 if triggers.empty else int(pd.to_numeric(triggers["conditions_excluded"], errors="coerce").sum())

    _render_topbar(
        "Tool 1 - Transmission Health Monitor",
        "Read the liquidity chain: upstream funding, friction layer, and downstream market liquidity.",
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(_card_html("Macro state", headline, f"Signal date {as_of}", headline), unsafe_allow_html=True)
    c2.markdown(_card_html("Active trigger", str(fired), "Narrative engine fire count", "stress" if fired else "easy"), unsafe_allow_html=True)
    c3.markdown(_card_html("Coverage gaps", str(excluded), "Excluded trigger conditions", "stress" if excluded else "easy"), unsafe_allow_html=True)
    c4.markdown(_card_html("MLI quality", _metric_value(latest, "MLI", "quality_score"), "Downstream data confidence", _metric_value(latest, "MLI", "quality_state")), unsafe_allow_html=True)

    fli = _index_row(latest, "FLI")
    mli = _index_row(latest, "MLI")
    fri = latest.loc[latest["index_name"].astype(str).str.startswith("FRI_")].copy() if not latest.empty else pd.DataFrame()
    binding_fri = None
    if not fri.empty:
        fri["index_value"] = pd.to_numeric(fri["index_value"], errors="coerce")
        binding_fri = fri.sort_values("index_value", ascending=False).iloc[0]

    te = _index_row(latest, "TE")

    st.markdown('<div class="ltmm-section">Transmission chain</div>', unsafe_allow_html=True)
    n1, n2, n3, n4 = st.columns(4)
    if fli is not None:
        n1.markdown(
            _card_html(
                "Funding liquidity",
                _number(fli["index_value"]),
                f"FLI is {fli['state']} | quality {_number(fli['quality_score'])}",
                str(fli["state"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        n1.markdown(_card_html("Funding liquidity", "n/a", "FLI is missing", "muted"), unsafe_allow_html=True)

    if binding_fri is not None:
        n2.markdown(
            _card_html(
                "Binding friction",
                str(binding_fri["index_name"]),
                f"value {_number(binding_fri['index_value'])} | quality {_number(binding_fri['quality_score'])}",
                str(binding_fri["state"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        n2.markdown(_card_html("Binding friction", "n/a", "FRI is missing", "muted"), unsafe_allow_html=True)

    if mli is not None:
        n3.markdown(
            _card_html(
                "Market liquidity",
                _number(mli["index_value"]),
                f"MLI is {mli['state']} | quality {_number(mli['quality_score'])}",
                str(mli["state"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        n3.markdown(_card_html("Market liquidity", "n/a", "MLI is missing", "muted"), unsafe_allow_html=True)

    if te is not None:
        n4.markdown(
            _card_html(
                "Transmission Eff.",
                _number(te["index_value"]),
                f"TE is {te['state']} | quality {_number(te['quality_score'])}",
                str(te["state"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        n4.markdown(_card_html("Transmission Eff.", "n/a", "TE is missing", "muted"), unsafe_allow_html=True)

    st.markdown('<div class="ltmm-section">Index details</div>', unsafe_allow_html=True)
    if latest.empty:
        st.info("No index details available.")
    else:
        st.dataframe(latest[["index_name", "index_value", "state", "quality_score", "quality_state"]], width="stretch", hide_index=True)

    st.markdown('<div class="ltmm-section">Transmission components</div>', unsafe_allow_html=True)
    components = data.get("components", pd.DataFrame())
    if components.empty:
        st.info("No component data available.")
    else:
        detail = components.copy()
        detail["abs_driver"] = pd.to_numeric(detail["normalized_driver"], errors="coerce").abs()
        detail = detail.sort_values("abs_driver", ascending=False).drop(columns=["abs_driver"])
        st.dataframe(detail, width="stretch", hide_index=True)

def _render_trigger_cards(triggers: pd.DataFrame) -> None:
    if triggers.empty:
        st.info("No trigger evaluation available.")
        return
    rows = list(triggers.itertuples(index=False))
    for start in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[start:start + 3]):
            state = str(row.signal_state)
            ratio = f"{row.fresh_conditions_met}/{row.fresh_conditions_total}"
            excluded = pd.to_numeric(pd.Series([row.conditions_excluded]), errors="coerce").iloc[0]
            caption = f"{ratio} conditions met | excluded {int(excluded) if pd.notna(excluded) else 0}"
            col.markdown(
                _card_html(str(row.trigger_id), state, caption, "stress" if state == "FIRE" else "easy"),
                unsafe_allow_html=True,
            )

def _render_tool2_bnd(data: dict[str, pd.DataFrame]) -> None:
    _render_topbar(
        "Tool 2 - Bottleneck Diagnostic",
        "Rank the binding constraint, then confirm it with narrative triggers and hard-gap footprints.",
    )
    bottlenecks = data.get("bottlenecks", pd.DataFrame())
    triggers = data.get("triggers", pd.DataFrame())
    overlays = data.get("overlays", pd.DataFrame())

    if bottlenecks.empty:
        st.info("No bottleneck data available.")
    else:
        top = bottlenecks.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.markdown(
            _card_html(
                "Primary bottleneck",
                str(top["constraint"]),
                f"score {_number(top['stress_score'])} | {top['state']}",
                str(top["state"]),
            ),
            unsafe_allow_html=True,
        )
        fired = 0 if triggers.empty else int(triggers["signal_state"].eq("FIRE").sum())
        c2.markdown(
            _card_html(
                "Narrative alerts",
                str(fired),
                "Active fire count",
                "stress" if fired else "easy",
            ),
            unsafe_allow_html=True,
        )
        high_overlay = overlays.dropna(subset=["stress_score"]).head(1) if not overlays.empty else pd.DataFrame()
        if high_overlay.empty:
            c3.markdown(_card_html("Footprint", "n/a", "No overlay data", "muted"), unsafe_allow_html=True)
        else:
            item = high_overlay.iloc[0]
            c3.markdown(
                _card_html(
                    "Strongest footprint",
                    str(item["overlay"]),
                    f"stress score {_number(item['stress_score'])}",
                    str(item["state"]),
                ),
                unsafe_allow_html=True,
            )

        st.markdown('<div class="ltmm-section">Constraint ranking</div>', unsafe_allow_html=True)
        rank = bottlenecks[["constraint", "layer", "stress_score", "state", "quality"]].copy()
        st.dataframe(rank, width="stretch", hide_index=True)
        chart = rank.dropna(subset=["stress_score"]).head(10).set_index("constraint")["stress_score"]
        st.bar_chart(chart)

    st.markdown('<div class="ltmm-section">Narrative signals</div>', unsafe_allow_html=True)
    _render_trigger_cards(triggers)
    with st.expander("Trigger decision table"):
        st.dataframe(triggers, width="stretch", hide_index=True)

    st.markdown('<div class="ltmm-section">Hard-gap and wedge footprints</div>', unsafe_allow_html=True)
    if overlays.empty:
        st.info("No overlay data available.")
    else:
        chart = overlays.dropna(subset=["stress_score"]).head(12).set_index("overlay")["stress_score"]
        st.bar_chart(chart)
        st.dataframe(
            overlays[["overlay", "node", "stress_score", "state", "quality_flag", "observation_date"]],
            width="stretch",
            hide_index=True,
        )

# --- AI CIO Renderer (Reads from AI_CIO_raw) ---

def _get_report_date(path: Path) -> dt.date:
    """Trích xuất ngày từ tên file để sắp xếp chính xác."""
    stem = path.stem
    # Tên có cấu trúc: ltmm_analyst_provider_ddmmyy
    parts = stem.split("_")
    if len(parts) >= 2:
        last_part = parts[-1]
        if last_part.isdigit() and len(last_part) == 6:
            try:
                return dt.datetime.strptime(last_part, "%d%m%y").date()
            except ValueError:
                pass
    # Định dạng DDMMYYYY
    if len(stem) == 8 and stem.isdigit():
        try:
            return dt.datetime.strptime(stem, "%d%m%Y").date()
        except ValueError:
            pass
    # Fallback theo st_mtime
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return dt.date.min


def _render_ai_cio(active_date: dt.date | None = None) -> None:
    _render_topbar(
        "🤖 AI CIO - Cố vấn LTMM",
        "Báo cáo phân tích chuyên sâu mô hình truyền dẫn LTMM và khuyến nghị phân bổ tài sản vĩ mô.",
    )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _all_caches = list(RAW_DIR.glob("*.txt")) + list(RAW_DIR.glob("*.md"))

    # Sắp xếp các báo cáo theo ngày thực tế trích xuất từ tên file (mới nhất lên trước)
    sorted_caches = sorted(_all_caches, key=_get_report_date, reverse=True)

    _options = {}
    for path in sorted_caches:
        stem = path.stem
        # Extract date details if matching standard formats
        parts = stem.split("_")
        if len(parts) >= 4 and parts[3].isdigit():
            prov = parts[2]
            date_part = parts[3]
            date_str = f"{date_part[:2]}/{date_part[2:4]}/20{date_part[4:]}"
            label = f"📅 {date_str} — 🤖 {'Kimi 2.6' if prov == 'kimi-2.6' else 'DeepSeek V4 Pro'}"
        elif len(stem) == 8 and stem.isdigit():
            # DDMMYYYY format
            label = f"📅 {stem[:2]}/{stem[2:4]}/{stem[4:]} — Báo cáo Thủ công"
        else:
            label = f"📄 {path.name}"
        _options[label] = path

    if not _options:
        st.info("ℹ️ Chưa tìm thấy báo cáo AI CIO nào trong thư mục data_lake/data_LTMM/AI_CIO_raw/")
        st.markdown(
            """
            > **Hướng dẫn:**  
            > Hãy dán các tệp báo cáo định dạng `.txt` hoặc `.md` (được đặt tên dạng `DDMMYYYY.md` hoặc tệp xuất tự động từ hệ thống LTMM) 
            > vào thư mục `data_lake/data_LTMM/AI_CIO_raw/` để hiển thị tại đây.
            """
        )
    else:
        # Tìm chỉ mục (index) của báo cáo khớp với ngày được chọn ở Sidebar
        default_index = 0
        if active_date is not None:
            for idx, (label, path) in enumerate(_options.items()):
                if _get_report_date(path) == active_date:
                    default_index = idx
                    break

        # Sử dụng key động theo active_date để tự động cập nhật selectbox khi đổi ngày ở sidebar
        selectbox_key = f"cio_history_select_{active_date.strftime('%Y%m%d') if active_date else 'default'}"

        _selected_label = st.selectbox(
            "Chọn báo cáo AI CIO để đọc:",
            options=list(_options.keys()),
            index=default_index,
            key=selectbox_key,
        )
        selected_path = _options[_selected_label]
        with open(selected_path, "r", encoding="utf-8") as f:
            report_text = f.read()

        with st.container(border=True):
            st.markdown(report_text)

# --- Main App Orchestrator ---

def render() -> None:
    _inject_styles()

    st.sidebar.markdown("### 📊 Bộ lọc LTMM")

    # --- 1. Scan and parse available dates in sourse_raw ---
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    json_files = list(SOURCE_DIR.glob("*.json"))

    def _parse_file_date(path: Path) -> dt.date:
        """Parse DDMMYYYY from filename; return date.min if unparseable."""
        stem = path.stem
        if len(stem) == 8 and stem.isdigit():
            try:
                return dt.datetime.strptime(stem, "%d%m%Y").date()
            except ValueError:
                pass
        return dt.date.min

    json_options = {}
    for path in sorted(json_files, key=_parse_file_date, reverse=True):
        stem = path.stem
        if len(stem) == 8 and stem.isdigit():
            label = f"📅 {stem[:2]}/{stem[2:4]}/{stem[4:]}"
        else:
            label = f"📄 {path.name}"
        json_options[label] = path

    # --- 2. Render Sidebar Option selector ---
    if not json_options:
        st.sidebar.warning("⚠️ Không tìm thấy file JSON data nào trong sourse_raw")
        st.info("ℹ️ Thư mục sourse_raw trống. Vui lòng thêm tệp JSON định dạng `DDMMYYYY.json` vào data_lake/data_LTMM/sourse_raw/.")
        st.stop()

    selected_date_label = st.sidebar.selectbox(
        "Chọn ngày phân tích:",
        options=list(json_options.keys()),
        index=0,  # Luôn mặc định chọn ngày gần nhất
        key="platform_date_select",
    )
    active_json_path = json_options[selected_date_label]

    # --- 3. Load selected raw JSON into DataFrames ---
    try:
        with open(active_json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
        data = {}
        for key, value in raw_data.items():
            if isinstance(value, list):
                data[key] = pd.DataFrame(value)
            else:
                data[key] = value
    except Exception as e:
        st.error(f"❌ Lỗi khi đọc file JSON dữ liệu: {e}")
        st.stop()

    st.sidebar.download_button(
        "Tải hướng dẫn đọc tool (.txt)",
        data=build_result_handout_text(data),
        file_name="hướng_dẫn_đọc_kết_quả_ltmm.txt",
        mime="text/plain; charset=utf-8",
        use_container_width=True,
    )

    # Trích xuất ngày đang được lựa chọn từ file JSON hoạt động
    active_date = None
    json_stem = active_json_path.stem
    if len(json_stem) == 8 and json_stem.isdigit():
        try:
            active_date = dt.datetime.strptime(json_stem, "%d%m%Y").date()
        except ValueError:
            pass

    # --- 4. Route views inside Tabs in main page area ---
    tab1, tab2, tab3 = st.tabs([
        "📊 Tool 1 - THM (Health Monitor)",
        "🔍 Tool 2 - BND (Bottleneck Diagnostic)",
        "🤖 AI CIO Analyst Report"
    ])

    with tab1:
        _render_tool1_thm(data)
    with tab2:
        _render_tool2_bnd(data)
    with tab3:
        _render_ai_cio(active_date)

if __name__ == "__main__":
    st.set_page_config(page_title="Quant Platform Integration", layout="wide")
    render()
