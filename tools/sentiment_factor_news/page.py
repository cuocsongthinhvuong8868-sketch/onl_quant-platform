from __future__ import annotations

import os
from collections import Counter
from datetime import date
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from config import AI_PROVIDER_MAP, AI_TEMPERATURE, DATA_LAKE
from shared.api_key_helper import resolve_api_key
from shared.llm_policy import completion_options
from tools.sentiment_factor_news import config
from tools.sentiment_factor_news.report import (
    FEED_DIR,
    build_sentiment_factor_news_ai_prompt,
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


def _run_ingestion(
    source: str,
    limit_mozyfin: int,
    limit_mozyfin_social: int,
    limit_widata: int,
    social_track: str | None,
):
    from tools.sentiment_factor_news.engine import run_ingestion

    args = SimpleNamespace(
        source=source,
        limit_mozyfin=limit_mozyfin,
        limit_mozyfin_social=limit_mozyfin_social,
        limit_widata=limit_widata,
        social_track=social_track,
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
    composite_prob = float(feed.get("macro_composite_prob_pos", 0.5))
    composite_prob_positive = float(feed.get("macro_composite_prob_positive", 0.5))
    macro_posterior = feed.get("macro_composite_posterior", {}) or {}
    source_counts = feed.get("source_counts", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Generated at", feed.get("generated_at", "N/A"))
    c2.metric("Regime", REGIME_LABELS.get(regime, regime))
    c3.metric(
        f"Composite (P_conf: {composite_prob:.1%})",
        f"{composite:+.3f}",
        help=(
            "Posterior mean of latent news sentiment. P_conf is same-direction posterior "
            "confidence, not probability of VNINDEX rising."
        ),
    )
    c4.metric("News count", int(feed.get("news_count", 0) or 0))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Mozyfin", int(source_counts.get("mozyfin", 0) or 0))
    c6.metric("Mozyfin Social", int(source_counts.get("mozyfin_social", 0) or 0))
    c7.metric("WiData", int(source_counts.get("widata", 0) or 0))
    c8.metric(
        "P(sentiment > 0)",
        f"{composite_prob_positive:.1%}",
        help="Posterior probability that latent news sentiment mean is positive.",
    )
    st.caption(
        "Composite posterior 90% CI: "
        f"{float(macro_posterior.get('ci_5', 0.0)):+.3f} to "
        f"{float(macro_posterior.get('ci_95', 0.0)):+.3f}; "
        f"posterior sd={float(macro_posterior.get('posterior_sd', 0.0)):.3f}."
    )

    st.divider()
    scores = feed.get("channel_scores", {})
    probs = feed.get("channel_probs", {})
    posteriors = feed.get("channel_posteriors", {})
    if scores:
        df_scores = (
            pd.DataFrame([
                {
                    "channel": k,
                    "score": float(v),
                    "prob_conf": float(probs.get(k, 0.5)),
                    "prob_positive": float((posteriors.get(k, {}) or {}).get("prob_positive", 0.5)),
                    "ci_5": float((posteriors.get(k, {}) or {}).get("ci_5", 0.0)),
                    "ci_95": float((posteriors.get(k, {}) or {}).get("ci_95", 0.0)),
                }
                for k, v in scores.items()
            ])
            .sort_values("score", ascending=False)
            .set_index("channel")
        )
        st.subheader("Sentiment Posterior by Macro Channel")
        st.bar_chart(df_scores["score"])
        st.dataframe(
            df_scores.reset_index().style.format({
                "score": "{:+.3f}",
                "prob_conf": "{:.1%}",
                "prob_positive": "{:.1%}",
                "ci_5": "{:+.3f}",
                "ci_95": "{:+.3f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

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


def _social_sentiment_label(item: dict) -> str:
    raw = str(item.get("raw_impact") or "").lower()
    if raw == "bullish":
        return "BULLISH"
    if raw == "bearish":
        return "BEARISH"
    return str(item.get("sentiment_label") or "neutral").upper()


def _render_social_posts(news_stream: list[dict], query: str):
    social_items = [item for item in news_stream if item.get("source_system") == "mozyfin_social"]
    if query:
        q = query.lower()
        social_items = [
            item for item in social_items
            if q in str(item.get("title", "")).lower()
            or q in str(item.get("summary", "")).lower()
            or q in str(item.get("source_name", "")).lower()
            or q in " ".join(str(entity) for entity in (item.get("entities") or [])).lower()
        ]

    if not social_items:
        st.info("No Mozyfin social posts in the current classified feed. Run ingestion with source `mozyfin_social`.")
        return

    rows = []
    all_entities = []
    for item in social_items:
        entities = item.get("entities") or []
        all_entities.extend(entities)
        rows.append({
            "timestamp": item.get("timestamp_vn", ""),
            "sender": item.get("sender_name") or item.get("source_name", "N/A"),
            "writing_track": item.get("writing_track") or "",
            "category": item.get("social_category") or item.get("raw_category") or "",
            "sentiment": _social_sentiment_label(item),
            "macro_channel": item.get("macro_channel", "unknown"),
            "score": float(item.get("final_score", 0.0) or 0.0),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "entities": entities,
            "url": item.get("url", ""),
        })

    df = pd.DataFrame(rows).sort_values("timestamp", ascending=False)
    total_posts = len(df)
    bullish_count = int((df["sentiment"] == "BULLISH").sum())
    bearish_count = int((df["sentiment"] == "BEARISH").sum())
    entity_counts = Counter(all_entities)
    top_ticker, top_ticker_count = entity_counts.most_common(1)[0] if entity_counts else ("N/A", 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Social posts", total_posts)
    c2.metric("Bullish", f"{bullish_count / total_posts:.1%}", f"{bullish_count} posts")
    c3.metric("Bearish", f"{bearish_count / total_posts:.1%}", f"{bearish_count} posts")
    c4.metric("Top ticker", top_ticker, f"{top_ticker_count} mentions")

    left, right = st.columns(2)
    with left:
        st.subheader("Sentiment Mix")
        st.bar_chart(df["sentiment"].value_counts())
        st.subheader("Writing Track")
        st.bar_chart(df["writing_track"].replace("", "unknown").value_counts().head(10))
    with right:
        st.subheader("Top Senders")
        st.bar_chart(df["sender"].value_counts().head(10))
        st.subheader("Top Mentioned Tickers")
        if entity_counts:
            st.bar_chart(pd.Series(dict(entity_counts.most_common(10))))
        else:
            st.info("No ticker/entity mentions found.")

    st.divider()
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    with f1:
        track_options = ["All"] + sorted([value for value in df["writing_track"].dropna().unique() if value])
        selected_track = st.selectbox("Writing track", track_options, key="social_writing_track_filter")
    with f2:
        category_options = ["All"] + sorted([value for value in df["category"].dropna().unique() if value])
        selected_category = st.selectbox("Category", category_options, key="social_category_filter")
    with f3:
        sentiment_options = ["All"] + sorted([value for value in df["sentiment"].dropna().unique() if value])
        selected_sentiment = st.selectbox("Sentiment", sentiment_options, key="social_sentiment_filter")
    with f4:
        local_query = st.text_input("Search social posts", key="social_local_search")

    filtered = df.copy()
    if selected_track != "All":
        filtered = filtered[filtered["writing_track"] == selected_track]
    if selected_category != "All":
        filtered = filtered[filtered["category"] == selected_category]
    if selected_sentiment != "All":
        filtered = filtered[filtered["sentiment"] == selected_sentiment]
    if local_query:
        q = local_query.lower()
        filtered = filtered[
            filtered["title"].str.lower().str.contains(q, na=False)
            | filtered["summary"].str.lower().str.contains(q, na=False)
            | filtered["sender"].str.lower().str.contains(q, na=False)
        ]

    st.caption(f"Showing {len(filtered)} matching social posts.")
    for row in filtered.head(100).to_dict("records"):
        label = f"{row['sentiment']} | {row['sender']} | {row['title']}"
        with st.expander(label):
            st.markdown(f"**Published:** {row['timestamp']}")
            st.markdown(
                f"**Track:** `{row['writing_track'] or 'unknown'}` | "
                f"**Category:** `{row['category'] or 'unknown'}` | "
                f"**Channel:** `{row['macro_channel']}` | "
                f"**Score:** `{row['score']:+.3f}`"
            )
            if row["entities"]:
                st.markdown(f"**Entities:** {', '.join(row['entities'])}")
            st.markdown(str(row["summary"] or ""))
            if row["url"]:
                st.markdown(f"[Original link]({row['url']})")


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


def _render_ai_analysis(ai_provider: str, api_key: str):
    st.subheader("AI Analysis - News Sentiment Factor")

    from openai import OpenAI

    today_str = date.today().strftime("%d%m%y")
    ai_cache_file = DATA_LAKE / "daily_cache" / f"sentiment_factor_news_{ai_provider}_{today_str}.txt"

    tab_current, tab_history = st.tabs(["Current analysis", "History"])

    with tab_current:
        if ai_cache_file.exists():
            st.success("Loaded AI analysis from daily cache.")
            with ai_cache_file.open("r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="sentiment_factor_news")

            if st.button("Run AI analysis again", type="secondary", key="sentiment_factor_news_rerun_ai"):
                os.remove(ai_cache_file)
                st.rerun()
        else:
            provider_name = AI_PROVIDER_MAP[ai_provider]["display"]
            btn_label = f"Run News Sentiment AI Analysis ({provider_name})"
            if st.button(btn_label, type="primary", use_container_width=True, key="sentiment_factor_news_run_ai"):
                if not api_key:
                    st.error("API key is missing. Enter it in the sidebar.")
                else:
                    with st.spinner("AI is reading the news sentiment factor feed..."):
                        try:
                            cfg = AI_PROVIDER_MAP[ai_provider]
                            client = OpenAI(
                                api_key=api_key.strip(),
                                base_url=cfg["base_url"],
                                timeout=cfg.get("timeout", 180),
                            )
                            system_prompt, user_prompt = build_sentiment_factor_news_ai_prompt()
                            response = client.chat.completions.create(
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt},
                                ],
                                **completion_options(
                                    model=cfg["api_model"],
                                    route="child_report",
                                    temperature=cfg.get("temperature", AI_TEMPERATURE),
                                ),
                            )
                            result_text = response.choices[0].message.content

                            ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                            ai_cache_file.write_text(result_text, encoding="utf-8")

                            st.success("AI analysis completed.")
                            with st.container(border=True):
                                st.markdown(result_text)
                        except Exception as exc:
                            st.error(f"AI API call failed: {exc}")

    with tab_history:
        from shared.history_selector import build_history_options

        cache_files = list(DATA_LAKE.glob("daily_cache/sentiment_factor_news_*.txt"))
        options = build_history_options(cache_files, "sentiment_factor_news", AI_PROVIDER_MAP)
        if not options:
            st.info("No historical AI analysis cache yet.")
        else:
            selected_label = st.selectbox(
                "Select date and model:",
                options=list(options.keys()),
                index=0,
                key="sentiment_factor_news_history_selector",
            )
            selected_path = options[selected_label]
            with st.container(border=True):
                try:
                    st.markdown(selected_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    st.error(f"Could not read cache file: {exc}")


def render():
    st.title("News Sentiment Factor Monitor")
    st.caption("Rule-based Vietnam macro/news/social sentiment feed from Mozyfin and WiData signals.")

    st.sidebar.header("News Sentiment Feed")
    window = st.sidebar.radio("Window", ["1d", "7d", "30d"], horizontal=True, key="sentiment_window")
    source_filter = st.sidebar.selectbox(
        "Source filter",
        ["All", "mozyfin", "mozyfin_social", "widata"],
        key="sentiment_source_filter",
    )
    query = st.sidebar.text_input("Search", key="sentiment_search")

    st.sidebar.divider()
    st.sidebar.subheader("Ingestion")
    source = st.sidebar.selectbox(
        "Fetch source",
        ["all", "mozyfin", "mozyfin_social", "widata"],
        key="sentiment_fetch_source",
    )
    limit_mozyfin = st.sidebar.number_input(
        "Mozyfin limit",
        min_value=1,
        max_value=100,
        value=config.FETCH_LIMIT_MOZYFIN,
        step=10,
    )
    limit_widata = st.sidebar.number_input(
        "WiData limit",
        min_value=1,
        max_value=5000,
        value=config.FETCH_LIMIT_WIDATA,
        step=100,
    )
    limit_mozyfin_social = st.sidebar.number_input(
        "Mozyfin social limit",
        min_value=1,
        max_value=100,
        value=config.FETCH_LIMIT_MOZYFIN_SOCIAL,
        step=10,
    )
    social_track = st.sidebar.text_input(
        "Social writing_track filter",
        key="sentiment_social_track",
        placeholder="Optional, e.g. MARKET_INSIGHT",
    )
    if st.sidebar.button("Run ingestion", use_container_width=True, key="sentiment_run_ingestion"):
        with st.spinner("Fetching and processing sentiment feed..."):
            try:
                _run_ingestion(
                    source,
                    int(limit_mozyfin),
                    int(limit_mozyfin_social),
                    int(limit_widata),
                    social_track.strip() or None,
                )
                st.success("Ingestion completed.")
                st.rerun()
            except Exception as exc:
                st.error(f"Ingestion failed: {exc}")

    st.sidebar.divider()
    st.sidebar.header("AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "Choose AI model",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="sentiment_factor_news_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key or 4-digit shortcut:",
        type="password",
        key="sentiment_factor_news_api_key",
        placeholder="sk-... or 1234",
    )
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    st.caption(f"Feed folder: `{FEED_DIR}`")

    feed = _load_feed_safe(window)
    news_stream = load_classified_news()
    tab_overview, tab_news, tab_social, tab_history, tab_ai, tab_snapshot = st.tabs(
        ["Overview", "News Feed", "Social Posts", "Timeline", "AI Analysis", "AI CIO Snapshot"]
    )

    with tab_overview:
        if feed:
            _render_overview(feed)

    with tab_news:
        _render_news_feed(news_stream, source_filter, query)

    with tab_social:
        _render_social_posts(news_stream, query)

    with tab_history:
        _render_timeline()

    with tab_ai:
        _render_ai_analysis(ai_provider, api_key)

    with tab_snapshot:
        snap = snapshot(window=window)
        st.json(snap)
