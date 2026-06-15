from __future__ import annotations

import os
from datetime import date
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from config import AI_PROVIDER_MAP, AI_TEMPERATURE, DATA_LAKE, ROOT_DIR
from shared.api_key_helper import resolve_api_key
from tools.vn100_earnings_health.quant.loader import (
    fill_prompt_template,
    fmt_num,
    fmt_pct,
    latest_period_rows,
    latest_valid,
    load_outputs,
    prepare_ai_payload,
)


PROMPT_PATH = ROOT_DIR / "promt" / "vn100_earnings_health_promt.md"
HANDBOOK_PATH = ROOT_DIR / "docs" / "vn100_earnings_health_handbook.txt"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .vn100-card {
            border: 1px solid rgba(128, 128, 128, 0.24);
            border-radius: 8px;
            padding: 0.72rem 0.82rem;
            min-height: 96px;
            box-sizing: border-box;
        }
        .vn100-card-label {
            color: rgba(80, 80, 80, 0.82);
            font-size: 0.78rem;
            line-height: 1.12;
            margin-bottom: 0.42rem;
        }
        .vn100-card-value {
            font-size: 1.02rem;
            font-weight: 650;
            line-height: 1.28;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .vn100-muted {
            color: rgba(100, 100, 100, 0.86);
            font-size: 0.86rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: object, min_height: int = 96) -> None:
    st.markdown(
        f"""
        <div class="vn100-card" style="min-height:{min_height}px">
            <div class="vn100-card-label">{escape(str(label))}</div>
            <div class="vn100-card-value">{escape(str(value))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _line_chart(
    df: pd.DataFrame,
    y: str,
    title: str,
    color: str | None = None,
    y_range: list[float] | None = None,
):
    fig = px.line(df, x="period", y=y, color=color, markers=True, title=title)
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=48, b=20))
    if y_range is not None:
        fig.update_yaxes(range=y_range)
    fig.add_hline(y=0, line_dash="dash", line_color="#777")
    return fig


def _component_delta(vn100: pd.DataFrame, column: str) -> str:
    valid = vn100.dropna(subset=[column]) if column in vn100.columns else pd.DataFrame()
    if len(valid) < 5:
        return "N/A"
    return fmt_num(valid.iloc[-1][column] - valid.iloc[-5][column], signed=True)


def _format_df(df: pd.DataFrame, digits: int = 3) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(digits)
    return out


def _render_ai_section(payload: dict[str, str], ai_provider: str, api_key: str) -> None:
    st.divider()
    st.subheader("✨ Trợ lý AI đọc VN100 Earnings Health")

    if not PROMPT_PATH.exists():
        st.warning(f"Không tìm thấy prompt: {PROMPT_PATH}")
        return

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    full_prompt = fill_prompt_template(prompt_template, payload)

    today_str = date.today().strftime("%d%m%y")
    ai_cache_file = DATA_LAKE / "daily_cache" / f"vn100_earnings_health_{ai_provider}_{today_str}.txt"

    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])

    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ cache ngày.")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            try:
                from shared.github_sync import render_sync_button

                render_sync_button(ai_cache_file, key_suffix="vn100_earnings_health")
            except Exception:
                pass

            if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="vn100_rerun_ai"):
                os.remove(ai_cache_file)
                st.rerun()
        else:
            btn_label = f"🐺 Phân tích VN100 ({AI_PROVIDER_MAP[ai_provider]['display']})"
            if st.button(btn_label, type="primary", width="stretch", key="vn100_run_ai"):
                if not api_key:
                    st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                else:
                    with st.spinner("AI đang đọc earnings cycle VN100..."):
                        try:
                            from openai import OpenAI

                            cfg = AI_PROVIDER_MAP[ai_provider]
                            client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))

                            parts = full_prompt.split("# INPUT DATA", 1)
                            system_prompt = parts[0].strip()
                            user_prompt = "# INPUT DATA" + parts[1] if len(parts) > 1 else full_prompt

                            response = client.chat.completions.create(
                                model=cfg["api_model"],
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt},
                                ],
                                temperature=cfg.get("temperature", AI_TEMPERATURE),
                            )
                            result_text = response.choices[0].message.content

                            ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(ai_cache_file, "w", encoding="utf-8") as f:
                                f.write(result_text)

                            st.success("Hoàn thành phân tích.")
                            with st.container(border=True):
                                st.markdown(result_text)
                        except Exception as e:
                            st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại.")

    with tab_history:
        from shared.history_selector import build_history_options

        cache_files = list(DATA_LAKE.glob("daily_cache/vn100_earnings_health_*.txt"))
        options = build_history_options(cache_files, "vn100_earnings_health", AI_PROVIDER_MAP)
        if not options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(options.keys()),
                index=0,
                key="vn100_history_selector",
            )
            with st.container(border=True):
                try:
                    st.markdown(options[selected_label].read_text(encoding="utf-8"))
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")


def render() -> None:
    _inject_css()

    col_title, col_handbook = st.columns([5, 1])
    with col_title:
        st.title("🇻🇳 VN100 Earnings Health")
        st.caption(
            "Fundamental bottom-up monitor cho VN100: Momentum + Breadth + Stability 12Q "
            "+ Profitability + CSAD blend + PCA validation."
        )
    with col_handbook:
        st.write("")
        if HANDBOOK_PATH.exists():
            st.download_button(
                label="📖 Tải Handbook",
                data=HANDBOOK_PATH.read_text(encoding="utf-8"),
                file_name="vn100_earnings_health_handbook.txt",
                mime="text/plain; charset=utf-8",
                width="stretch",
            )

    st.sidebar.header("🇻🇳 VN100 Earnings Health")
    history_quarters = st.sidebar.slider(
        "Số quý hiển thị",
        min_value=8,
        max_value=33,
        value=24,
        step=1,
        key="vn100_history_quarters",
    )
    if st.sidebar.button("🧹 Clear VN100 cache", key="vn100_clear_cache"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="vn100_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key (hoặc shortcut 4 số):",
        type="password",
        key="vn100_api_key",
        placeholder="sk-... hoặc 4 số",
    )
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    outputs = load_outputs()
    output_dir = outputs["output_dir"]
    vn100: pd.DataFrame = outputs["vn100"]
    sectors: pd.DataFrame = outputs["sectors"]
    tickers: pd.DataFrame = outputs["tickers"]
    csad: pd.DataFrame = outputs["csad"]
    pca: pd.DataFrame = outputs["pca"]
    parse_log: pd.DataFrame = outputs["parse_log"]
    failed_parse_log: pd.DataFrame = outputs["failed_parse_log"]

    st.caption(f"Data source: `{output_dir}`")

    if vn100.empty:
        st.error("Không tìm thấy output VN100. Hãy chạy pipeline VN100 hoặc kiểm tra data_lake fallback.")
        st.stop()
        return

    latest = latest_valid(vn100, "vn100_score")
    if latest is None:
        st.warning("Chưa có VN100 score hợp lệ. Kiểm tra coverage/data quality.")
        st.stop()
        return

    period = str(latest["period"])
    vn100_plot = vn100.tail(history_quarters).copy()

    try:
        payload = prepare_ai_payload(outputs)
    except Exception as e:
        payload = {}
        st.warning(f"Không build được AI payload: {e}")

    cols = st.columns(4)
    with cols[0]:
        _metric_card("VN100 Score", fmt_num(latest["vn100_score"], digits=3, signed=True))
    with cols[1]:
        _metric_card("Regime", latest.get("regime", "N/A"))
    with cols[2]:
        _metric_card("Coverage", fmt_pct(latest.get("coverage_ratio"), digits=0))
    with cols[3]:
        _metric_card("Broadness", latest.get("broadness_label", "N/A"))

    comp_cols = st.columns(5)
    component_cards = [
        ("Momentum", "momentum_score"),
        ("Breadth", "breadth_score"),
        ("Stability 12Q", "stability_score"),
        ("Profitability", "profitability_score"),
        ("CSAD Blend", "csad_quality_score"),
    ]
    for col, (label, field) in zip(comp_cols, component_cards):
        with col:
            _metric_card(label, fmt_num(latest.get(field), signed=True), min_height=86)

    st.plotly_chart(
        _line_chart(vn100_plot, "vn100_score", "VN100 Earnings Health Score", y_range=[-1, 1]),
        width="stretch",
    )

    if payload:
        failed = payload.get("failed_parse_tickers", "None")
        missing = payload.get("missing_score_tickers", "None")
        if failed == "None":
            st.success("Parse coverage: không có ticker data failed.")
        else:
            st.warning(f"Ticker data failed: {failed}")
        if missing != "None":
            st.info(f"Ticker thiếu score ở {period}: {missing}")

    tab_components, tab_sector, tab_breadth, tab_pca, tab_data = st.tabs(
        ["Component Trends", "Sector Map", "Breadth & CSAD", "PCA Validation", "Data Quality"]
    )

    with tab_components:
        component_map = {
            "Momentum": "momentum_score",
            "Breadth": "breadth_score",
            "Stability 12Q": "stability_score",
            "Profitability": "profitability_score",
            "CSAD Quality": "csad_quality_score",
        }
        trend = vn100_plot[["period", *component_map.values()]].melt(
            id_vars="period", var_name="component", value_name="score"
        )
        trend["component"] = trend["component"].map({v: k for k, v in component_map.items()})
        st.plotly_chart(
            _line_chart(trend.dropna(), "score", "Component Scores", color="component", y_range=[-1, 1]),
            width="stretch",
        )

        rows = []
        for name, col in component_map.items():
            rows.append(
                {
                    "Component": name,
                    "Current": latest.get(col),
                    "4Q Change": _component_delta(vn100, col),
                }
            )
        st.dataframe(_format_df(pd.DataFrame(rows)), hide_index=True, width="stretch")

        c1, c2 = st.columns(2)
        for idx, (name, col) in enumerate(component_map.items()):
            with (c1 if idx % 2 == 0 else c2):
                st.plotly_chart(
                    _line_chart(vn100_plot, col, name, y_range=[-1, 1]),
                    width="stretch",
                )

        if payload:
            _render_ai_section(payload, ai_provider, api_key)

    with tab_sector:
        current_sectors = latest_period_rows(sectors, period).copy()
        if current_sectors.empty:
            st.warning("Không có sector score cho kỳ hiện tại.")
        else:
            current_sectors = current_sectors.sort_values("sector_composite_score", ascending=False)
            st.subheader(f"Sector Ranking - {period}")
            st.dataframe(_format_df(current_sectors), hide_index=True, width="stretch")

            heat = current_sectors.pivot_table(
                index="sector", values="sector_composite_score", aggfunc="first"
            )
            fig = px.imshow(
                heat,
                color_continuous_scale="RdYlGn",
                zmin=-1,
                zmax=1,
                aspect="auto",
                title=f"Sector Composite Heatmap - {period}",
            )
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=48, b=20))
            st.plotly_chart(fig, width="stretch")

            sector_trend = sectors.tail(history_quarters * max(1, current_sectors["sector"].nunique()))
            st.plotly_chart(
                _line_chart(
                    sector_trend.dropna(subset=["sector_composite_score"]),
                    "sector_composite_score",
                    "Sector Composite Scores",
                    color="sector",
                    y_range=[-1, 1],
                ),
                width="stretch",
            )

    with tab_breadth:
        csad_plot = csad.tail(history_quarters).copy()
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(
                _line_chart(csad_plot, "breadth_score", "Breadth Score", y_range=[-1, 1]),
                width="stretch",
            )
        with c2:
            csad_quality_cols = {
                "Raw": "csad_quality_raw_score",
                "EMA 4Q": "csad_quality_ema_score",
                "Blend 65/35": "csad_quality_score",
            }
            if set(csad_quality_cols.values()).issubset(csad_plot.columns):
                csad_trend = csad_plot[["period", *csad_quality_cols.values()]].melt(
                    id_vars="period", var_name="series", value_name="score"
                )
                csad_trend["series"] = csad_trend["series"].map({v: k for k, v in csad_quality_cols.items()})
                st.plotly_chart(
                    _line_chart(csad_trend.dropna(), "score", "CSAD Quality: Raw vs EMA Blend", color="series", y_range=[-1, 1]),
                    width="stretch",
                )

        if not csad_plot.empty:
            fig = px.scatter(
                csad_plot,
                x="breadth_raw",
                y="csad_raw",
                color="quadrant_label",
                hover_data=["period", "positive_ticker_count", "negative_ticker_count"],
                title="Breadth vs CSAD Raw",
            )
            fig.add_vline(x=0.65, line_dash="dash", line_color="#777")
            fig.add_vline(x=0.45, line_dash="dash", line_color="#777")
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=48, b=20))
            st.plotly_chart(fig, width="stretch")

        latest_tickers = latest_period_rows(tickers, period)
        if not latest_tickers.empty and "ticker_health_score" in latest_tickers.columns:
            fig = px.histogram(
                latest_tickers,
                x="ticker_health_score",
                nbins=30,
                title=f"Ticker Health Score Distribution - {period}",
            )
            fig.update_layout(height=360, margin=dict(l=20, r=20, t=48, b=20))
            st.plotly_chart(fig, width="stretch")

    with tab_pca:
        if pca.empty:
            st.warning("PCA validation chưa có dữ liệu.")
        else:
            current_pca = latest_period_rows(pca, period)
            latest_pca = current_pca.iloc[-1] if not current_pca.empty else pca.iloc[-1]
            pca_cols = st.columns(5)
            with pca_cols[0]:
                _metric_card("PCA Factor Score", fmt_num(latest_pca.get("pca_factor_score"), signed=True))
            with pca_cols[1]:
                _metric_card("PC1 Explained Variance", fmt_pct(latest_pca.get("pc1_explained_variance"), digits=0))
            with pca_cols[2]:
                _metric_card("Corr EW vs PC1", fmt_num(latest_pca.get("corr_ew_composite_pc1"), digits=2))
            with pca_cols[3]:
                _metric_card("Common Factor", latest_pca.get("common_factor_label", "N/A"))
            with pca_cols[4]:
                _metric_card("One-sector Shock", latest_pca.get("one_factor_shock_flag", "N/A"))

            pca_plot = pca[["period", "pca_factor_score"]].merge(
                vn100[["period", "vn100_score"]], on="period", how="left"
            )
            pca_plot = pca_plot.tail(history_quarters).melt(
                id_vars="period", var_name="series", value_name="value"
            )
            fig = px.line(
                pca_plot,
                x="period",
                y="value",
                color="series",
                markers=True,
                title="PCA Common Factor Score vs VN100 Equal-weighted Composite",
            )
            fig.update_layout(height=380, margin=dict(l=20, r=20, t=48, b=20))
            fig.update_yaxes(range=[-1, 1])
            fig.add_hline(y=0, line_dash="dash", line_color="#777")
            st.plotly_chart(fig, width="stretch")

            loading_df = pd.DataFrame(
                {
                    "sector": [
                        latest_pca.get("dominant_sector_1", "N/A"),
                        latest_pca.get("dominant_sector_2", "N/A"),
                        latest_pca.get("dominant_sector_3", "N/A"),
                    ],
                    "loading": [
                        latest_pca.get("dominant_sector_1_loading"),
                        latest_pca.get("dominant_sector_2_loading"),
                        latest_pca.get("dominant_sector_3_loading"),
                    ],
                }
            )
            fig = px.bar(loading_df, x="sector", y="loading", title="Dominant PC1 Sector Loadings")
            fig.update_layout(height=360, margin=dict(l=20, r=20, t=48, b=20))
            st.plotly_chart(fig, width="stretch")

    with tab_data:
        st.subheader("Parse / Coverage")
        if not failed_parse_log.empty:
            st.warning("Ticker data failed")
            st.dataframe(failed_parse_log, hide_index=True, width="stretch")
        else:
            st.success("Không có ticker data failed trong failed_parse_log.")

        if payload:
            st.markdown(f"**Ticker thiếu score latest period:** {payload.get('missing_score_tickers', 'N/A')}")
            st.markdown(f"**Parsed tickers:** {payload.get('parsed_ticker_count', 'N/A')} / {payload.get('universe_ticker_count', 'N/A')}")

        if not parse_log.empty:
            status_counts = parse_log["parse_status"].value_counts().rename_axis("status").reset_index(name="count")
            st.dataframe(status_counts, hide_index=True, width="stretch")
            with st.expander("Parse log chi tiết"):
                st.dataframe(parse_log, hide_index=True, width="stretch")

        latest_tickers = latest_period_rows(tickers, period)
        if not latest_tickers.empty:
            with st.expander(f"Ticker metrics - {period}"):
                st.dataframe(_format_df(latest_tickers), hide_index=True, width="stretch")
