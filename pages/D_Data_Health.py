from __future__ import annotations

import sys
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.page_layout import setup_page, signal_card_html, signal_pill_html
from src.data_manager import DataManager


setup_page("Quant Platform - Data Health")


STATUS_ORDER = {"healthy": 0, "warning": 1, "critical": 2}
STATUS_LABELS = {
    "healthy": "Healthy",
    "warning": "Warning",
    "critical": "Critical",
}
STATUS_TONES = {
    "healthy": "positive",
    "warning": "warning",
    "critical": "danger",
}


@st.cache_data(show_spinner=False, ttl=60)
def _load_report(as_of: str) -> dict:
    manager = DataManager(as_of=pd.to_datetime(as_of).date())
    return manager.check_data_freshness()


@st.cache_data(show_spinner=False, ttl=60)
def _load_timeline(as_of: str, days: int) -> list[dict]:
    manager = DataManager(as_of=pd.to_datetime(as_of).date())
    return manager.build_timeline(days=days)


def _status_badge(status: str) -> str:
    label = STATUS_LABELS.get(status, status.title())
    return signal_pill_html(label, tone=STATUS_TONES.get(status, "neutral"))


def _render_summary(report: dict) -> None:
    summary = report["summary"]
    overall = report["overall_status"]
    cols = st.columns(4)
    with cols[0]:
        _render_card("Overall", STATUS_LABELS.get(overall, overall.title()), overall)
    with cols[1]:
        _render_card("Healthy", str(summary.get("healthy", 0)), "healthy")
    with cols[2]:
        _render_card("Warning", str(summary.get("warning", 0)), "warning")
    with cols[3]:
        _render_card("Critical", str(summary.get("critical", 0)), "critical")


def _render_card(title: str, value: str, status: str) -> None:
    st.markdown(
        signal_card_html(title, value, tone=STATUS_TONES.get(status, "neutral"), min_height=86),
        unsafe_allow_html=True,
    )


def _render_detail_table(report: dict, view: str = "Tool Metrics") -> None:
    rows = []
    for source in report["sources"]:
        rows.append(
            {
                "Source": source["name"],
                "Tool": source.get("tool"),
                "Category": source["category"],
                "Status": source["status"],
                "Latest Date": source.get("latest_data_date"),
                "Age Days": source.get("freshness_days"),
                "Warning": source.get("warning_days"),
                "Critical": source.get("critical_days"),
                "Dependencies": source.get("dependencies"),
                "Cache Date": source.get("cache_data_date"),
                "Cache": source.get("cache_status"),
                "Date Source": source.get("date_source"),
                "Files": source.get("file_count"),
                "Reason": source.get("status_reason"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No data sources are configured.")
        return

    if view == "Raw Data":
        frame = frame[frame["Category"].str.startswith("raw/", na=False)]
    elif view == "Processed Metrics":
        frame = frame[frame["Category"].str.startswith("processed/metrics", na=False)]
    elif view == "Tool Metrics":
        frame = frame[frame["Category"].str.startswith("processed/tool_metrics", na=False)]
    elif view == "Reports":
        frame = frame[frame["Category"].str.startswith("processed/reports", na=False)]

    if frame.empty:
        st.info(f"No rows for {view}.")
        return

    frame["_rank"] = frame["Status"].map(STATUS_ORDER).fillna(99)
    frame = frame.sort_values(["_rank", "Age Days", "Source"], ascending=[False, False, True]).drop(columns=["_rank"])

    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Status": st.column_config.TextColumn("Status"),
            "Age Days": st.column_config.NumberColumn("Age Days", format="%d"),
            "Warning": st.column_config.NumberColumn("Warning", format="%d"),
            "Critical": st.column_config.NumberColumn("Critical", format="%d"),
        },
    )


def _render_timeline(as_of: str, days: int) -> None:
    timeline = _load_timeline(as_of, days)
    frame = pd.DataFrame(timeline)
    if frame.empty:
        st.info("No timeline data is available.")
        return

    frame["Data"] = frame["has_data"].map({True: "Present", False: "Missing"})
    frame["date"] = pd.to_datetime(frame["date"])
    fig = px.scatter(
        frame,
        x="date",
        y="source",
        color="Data",
        color_discrete_map={"Present": "#15803d", "Missing": "#cbd5e1"},
        hover_data=["category"],
        height=max(360, min(780, 34 * frame["source"].nunique())),
    )
    fig.update_traces(marker={"size": 10})
    fig.update_layout(
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        xaxis_title="Date",
        yaxis_title="Source",
        legend_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def render() -> None:
    st.title("Data Health")
    st.caption("Data Management and Monitoring for data_lake raw, processed, and report files.")

    as_of_date = st.date_input("As of date", value=pd.Timestamp.today().date())
    as_of = as_of_date.isoformat()
    report = _load_report(as_of)

    _render_summary(report)
    st.markdown(_status_badge(report["overall_status"]), unsafe_allow_html=True)

    tab_status, tab_timeline, tab_export = st.tabs(["Status", "Timeline", "Export"])

    with tab_status:
        st.subheader("Source Status")
        view = st.radio(
            "Status view",
            ["Tool Metrics", "Raw Data", "Processed Metrics", "Reports", "All"],
            horizontal=True,
            label_visibility="collapsed",
        )
        _render_detail_table(report, view=view)

    with tab_timeline:
        st.subheader("Last 30 Days")
        days = st.slider("Timeline window", min_value=7, max_value=60, value=30, step=1)
        _render_timeline(as_of, days)

    with tab_export:
        st.subheader("JSON / CSV Report")
        json_payload = json.dumps(report, indent=2, ensure_ascii=False)
        st.download_button(
            "Download JSON",
            data=json_payload,
            file_name=f"data_health_{as_of}.json",
            mime="application/json",
            use_container_width=True,
        )

        csv_frame = pd.DataFrame(report["sources"])
        st.download_button(
            "Download CSV",
            data=csv_frame.to_csv(index=False),
            file_name=f"data_health_{as_of}.csv",
            mime="text/csv",
            use_container_width=True,
        )


render()
