from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st

from tools.sentiment_factor_news.report import (
    FEED_DIR,
    load_channel_scores,
    load_classified_news,
    load_feed,
    snapshot,
)


REGIME_LABELS = {
    "strong_risk_on": "Strong Risk-On",
    "risk_on": "Risk-On",
    "neutral": "Neutral",
    "risk_off": "Risk-Off",
    "strong_risk_off": "Strong Risk-Off",
}


def _run_ingestion(source: str, limit_mozyfin: int, limit_widata: int):
    from tools.sentiment_factor_news.engine import run_ingestion

    args = SimpleNamespace(
        source=source,
        limit_mozyfin=limit_mozyfin,
        limit_widata=limit_widata,
        publish_git=False,
    )
    run_ingestion(args)


def _load_feed_safe(window: str) -> dict | None:
    try:
        return load_feed(window)
    except Exception as exc:
        st.warning(f"Chưa có feed `{window}`: {exc}")
        return None


def _driver_frame(drivers: list[dict]) -> pd.DataFrame:
    if not drivers:
        return pd.DataFrame(columns=["timestamp", "macro_channel", "final_score", "source", "title", "url"])
    return pd.DataFrame(drivers)[["timestamp", "macro_channel", "final_score", "source", "title", "url"]]


def _render_overview(feed: dict):
    regime = feed.get("regime", "neutral")
    composite = float(feed.get("macro_composite", 0.0) or 0.0)
    source_counts = feed.get("source_counts", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Generated at", feed.get("generated_at", "N/A"))
    c2.metric("Regime", REGIME_LABELS.get(regime, regime))
    c3.metric("Composite", f"{composite:+.3f}", help="Weighted composite, range roughly -0.5 to +0.5.")
    c4.metric("News count", int(feed.get("news_count", 0) or 0))

    c5, c6 = st.columns(2)
    c5.metric("Mozyfin", int(source_counts.get("mozyfin", 0) or 0))
    c6.metric("WiData", int(source_counts.get("widata", 0) or 0))

    st.divider()
    scores = feed.get("channel_scores", {})
    if scores:
        df_scores = (
            pd.DataFrame([{"channel": k, "score": float(v)} for k, v in scores.items()])
            .sort_values("score", ascending=False)
            .set_index("channel")
        )
        st.subheader("Sentiment Score by Macro Channel")
        st.bar_chart(df_scores)
        st.dataframe(df_scores.reset_index(), use_container_width=True, hide_index=True)

    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Top Positive Drivers")
        st.dataframe(_driver_frame(feed.get("top_positive_drivers", [])), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Top Negative Drivers")
        st.dataframe(_driver_frame(feed.get("top_negative_drivers", [])), use_container_width=True, hide_index=True)


def _render_news_feed(news_stream: list[dict], source_filter: str, query: str):
    channels = ["All"] + sorted({item.get("macro_channel", "unknown") for item in news_stream})
    selected_channel = st.selectbox("Macro channel", channels, key="sentiment_news_channel")

    filtered = news_stream
    if selected_channel != "All":
        filtered = [item for item in filtered if item.get("macro_channel") == selected_channel]
    if source_filter != "All":
        filtered = [item for item in filtered if item.get("source_system") == source_filter]
    if query:
        q = query.lower()
        filtered = [
            item for item in filtered
            if q in str(item.get("title", "")).lower() or q in str(item.get("summary", "")).lower()
        ]

    st.caption(f"Showing {len(filtered)} matching news items.")
    for item in filtered[:100]:
        score = float(item.get("final_score", 0.0) or 0.0)
        title = item.get("title", "N/A")
        source = item.get("source_name", item.get("source_system", "N/A"))
        with st.expander(f"{score:+.2f} · {source} · {title}"):
            st.markdown(f"**Published:** {item.get('timestamp_vn', 'N/A')}")
            st.markdown(
                f"**Channel:** `{item.get('macro_channel', 'unknown')}` · "
                f"**Event:** `{item.get('event_type', 'unknown')}` · "
                f"**Horizon:** `{item.get('horizon', 'unknown')}`"
            )
            transmissions = item.get("market_transmission") or []
            if transmissions:
                st.markdown(f"**Transmission:** `{', '.join(transmissions)}`")
            entities = item.get("entities") or []
            if entities:
                st.markdown(f"**Entities:** {', '.join(entities)}")
            st.markdown(str(item.get("summary", "")))
            url = item.get("url")
            if url:
                st.markdown(f"[Original link]({url})")


def _render_timeline():
    scores = load_channel_scores()
    if scores.empty:
        st.info("Chưa có timeline. Chạy ingestion nhiều lần để tạo lịch sử.")
        return

    window = st.selectbox("Window", ["latest_1d", "latest_7d", "latest_30d"], key="sentiment_timeline_window")
    df = scores[scores["window"] == window].copy()
    if df.empty:
        st.info(f"Không có timeline cho `{window}`.")
        return

    pivot = df.pivot_table(index="generated_at", columns="channel", values="score", aggfunc="last").fillna(0.0)
    weights = {
        "liquidity": 0.20,
        "banking_system": 0.175,
        "credit_stress": 0.15,
        "fx_external": 0.125,
        "real_estate_collateral": 0.125,
        "monetary_policy": 0.10,
        "growth": 0.075,
        "fiscal_public_investment": 0.05,
    }
    pivot["COMPOSITE_INDEX"] = sum(pivot.get(channel, 0.0) * weight for channel, weight in weights.items())
    default_cols = [col for col in ["COMPOSITE_INDEX", "liquidity", "fx_external", "credit_stress"] if col in pivot.columns]
    selected = st.multiselect("Series", list(pivot.columns), default=default_cols)
    if selected:
        st.line_chart(pivot[selected])
        st.dataframe(pivot[selected].sort_index(ascending=False), use_container_width=True)


def render():
    st.title("News Sentiment Factor Monitor")
    st.caption("Rule-based Vietnam macro/news sentiment feed from Mozyfin and WiData signals.")

    st.sidebar.header("News Sentiment Feed")
    window = st.sidebar.radio("Window", ["1d", "7d", "30d"], horizontal=True, key="sentiment_window")
    source_filter = st.sidebar.selectbox("Source filter", ["All", "mozyfin", "widata"], key="sentiment_source_filter")
    query = st.sidebar.text_input("Search", key="sentiment_search")

    st.sidebar.divider()
    st.sidebar.subheader("Ingestion")
    source = st.sidebar.selectbox("Fetch source", ["all", "mozyfin", "widata"], key="sentiment_fetch_source")
    limit_mozyfin = st.sidebar.number_input("Mozyfin limit", min_value=1, max_value=10000, value=100, step=25)
    limit_widata = st.sidebar.number_input("WiData limit", min_value=1, max_value=1000, value=50, step=25)
    if st.sidebar.button("Run ingestion", use_container_width=True, key="sentiment_run_ingestion"):
        with st.spinner("Fetching and processing sentiment feed..."):
            try:
                _run_ingestion(source, int(limit_mozyfin), int(limit_widata))
                st.success("Ingestion completed.")
                st.rerun()
            except Exception as exc:
                st.error(f"Ingestion failed: {exc}")

    st.caption(f"Feed folder: `{FEED_DIR}`")

    feed = _load_feed_safe(window)
    news_stream = load_classified_news()
    tab_overview, tab_news, tab_history, tab_snapshot = st.tabs(
        ["Overview", "News Feed", "Timeline", "AI CIO Snapshot"]
    )

    with tab_overview:
        if feed:
            _render_overview(feed)

    with tab_news:
        _render_news_feed(news_stream, source_filter, query)

    with tab_history:
        _render_timeline()

    with tab_snapshot:
        snap = snapshot(window=window)
        st.json(snap)
