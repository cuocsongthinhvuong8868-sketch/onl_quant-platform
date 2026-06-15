from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from config import AI_PROVIDER_MAP, DATA_LAKE
from shared.api_key_helper import resolve_api_key
from shared.daily_cache import load_daily_cache, save_daily_cache
from shared.data_loader import load_close_prices, load_volumes
from shared.history_selector import build_history_options
from shared.page_layout import render_signal_card
from tools.bank_valuation.quant.engine.ai_analysis import run_ai_analysis
from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime
from tools.bank_valuation.quant.pipeline import (
    BCTC_JSON_DIR,
    bank_valuation_source_signature,
    run_bank_valuation_pipeline,
)
from tools.bank_valuation.quant.summary import (
    CLASSIFICATION_LABELS_VI,
    classification_summary,
    fmt_number,
    fmt_pct,
    latest_period,
)
from tools.bank_valuation.ui.charts import (
    plot_classification_breadth,
    plot_gap_vs_risk,
    plot_market_confirmation,
    plot_valuation_gap,
)


def _ai_cache_file(provider_key: str, run_date: date | None = None) -> Path:
    run_date = run_date or date.today()
    return DATA_LAKE / "daily_cache" / f"bank_valuation_ai_{provider_key}_{run_date.strftime('%d%m%y')}.txt"


def _classification_label_vi(value: str) -> str:
    return CLASSIFICATION_LABELS_VI.get(str(value), str(value))


def _classification_counts(data: pd.DataFrame) -> dict[str, int]:
    labels = data["classification"].fillna("") if "classification" in data.columns else pd.Series(dtype=str)
    return {
        "overvalued": int((labels == "Overvalued").sum()),
        "fair": int((labels == "Fairly Valued").sum()),
        "under": int(labels.isin(["Strong Undervalued", "Undervalued but Risky"]).sum()),
    }


def _confirmation_universe(data: pd.DataFrame) -> pd.DataFrame:
    if "classification" not in data.columns:
        return data.iloc[0:0].copy()
    keep = data["classification"].isin(["Fairly Valued", "Strong Undervalued", "Undervalued but Risky"])
    return data[keep].copy()


def _tone_for_regime(label: str) -> str:
    text = str(label).lower()
    if "cao trên diện rộng" in text:
        return "danger"
    if "cao" in text:
        return "warning"
    if "rẻ" in text:
        return "positive"
    if "chưa đủ" in text:
        return "neutral"
    return "info"


def _render_overview(data: pd.DataFrame) -> None:
    st.header("Tổng Quan Định Giá")
    regime = calculate_bank_valuation_regime(data)
    counts = _classification_counts(data)
    low_risk = data.dropna(subset=["overall_risk_score"]).sort_values("overall_risk_score").head(1)
    high_gap = data.dropna(subset=["valuation_gap_pct"]).sort_values("valuation_gap_pct", ascending=False).head(1)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_signal_card(
            "Tín hiệu định giá",
            f"{len(data)} ngân hàng niêm yết",
            tone="info",
            caption=f"Cao: {counts['overvalued']} | Hợp lý: {counts['fair']} | Rẻ/rủi ro: {counts['under']}",
            min_height=100,
        )
    with col2:
        render_signal_card(
            "Regime từ định giá banks",
            regime.regime_label,
            tone=_tone_for_regime(regime.regime_label),
            caption=f"Điểm độ rộng: {fmt_number(regime.bank_valuation_breadth_score)}",
            min_height=100,
        )
    with col3:
        render_signal_card(
            "Rủi ro thấp nhất",
            "n/a" if low_risk.empty else str(low_risk.iloc[0]["ticker"]),
            tone="neutral",
            caption="n/a" if low_risk.empty else f"{fmt_number(low_risk.iloc[0]['overall_risk_score'])} điểm rủi ro",
            min_height=100,
        )
    with col4:
        render_signal_card(
            "Gap cao nhất",
            "n/a" if high_gap.empty else str(high_gap.iloc[0]["ticker"]),
            tone="positive",
            caption="n/a" if high_gap.empty else fmt_pct(high_gap.iloc[0]["valuation_gap_pct"], signed=True),
            min_height=100,
        )

    chart = plot_gap_vs_risk(data)
    if chart is not None:
        st.plotly_chart(chart, use_container_width=True)

    st.subheader("Xác nhận giá")
    confirmation_df = _confirmation_universe(data)
    if confirmation_df.empty:
        st.info("Không có nhóm hợp lý/rẻ để kiểm tra xác nhận giá.")
        return

    chart = plot_market_confirmation(confirmation_df)
    if chart is not None:
        st.plotly_chart(chart, use_container_width=True)
    else:
        st.info("Chưa có đủ market data để vẽ xác nhận giá.")

    display_cols = [
        "ticker",
        "period",
        "price",
        "beta",
        "market_close",
        "valuation_gap_pct",
        "classification",
        "overall_risk_score",
        "market_confirmation_score",
        "market_confirmation_label",
        "data_quality_flag",
        "relative_valuation_label",
        "market_mispricing_score",
    ]
    display_cols = [col for col in display_cols if col in confirmation_df.columns]
    st.dataframe(
        confirmation_df[display_cols].style.format(
            {
                "price": "{:,.0f}",
                "beta": "{:.2f}",
                "market_close": "{:,.0f}",
                "valuation_gap_pct": "{:.1%}",
                "overall_risk_score": "{:.1f}",
                "market_confirmation_score": "{:.1f}",
                "market_mispricing_score": "{:.1%}",
            },
            na_rep="n/a",
        ),
        use_container_width=True,
    )


def _render_market_regime(data: pd.DataFrame) -> None:
    regime = calculate_bank_valuation_regime(data)

    st.header("Trạng Thái Thị Trường")
    st.caption(
        "Hàm ý từ độ rộng định giá nhóm ngân hàng, không dựa trên P/E thị trường "
        "hay tín hiệu kỹ thuật của chỉ số."
    )
    st.info(regime.methodology_note)

    if regime.eligible_banks == 0:
        st.warning("Chưa đủ dữ liệu định giá ngân hàng để suy ra trạng thái thị trường.")
        return

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        render_signal_card("Mã hợp lệ", regime.eligible_banks, tone="neutral", caption="Không tính Low quality")
    with col2:
        render_signal_card("Định giá cao", regime.overvalued_count, tone="danger", caption=fmt_pct(regime.overvalued_breadth))
    with col3:
        render_signal_card("Hợp lý", regime.fair_count, tone="neutral", caption=fmt_pct(regime.fair_breadth))
    with col4:
        render_signal_card("Rẻ / rủi ro", regime.undervalued_count, tone="positive", caption=fmt_pct(regime.undervalued_breadth))
    with col5:
        render_signal_card(
            "Điểm độ rộng",
            fmt_pct(regime.bank_valuation_breadth_score, signed=True),
            tone=_tone_for_regime(regime.regime_label),
            caption=regime.regime_label,
        )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Gap trung vị", fmt_pct(regime.median_valuation_gap, signed=True))
    m2.metric("Gap trimmed mean", fmt_pct(regime.trimmed_mean_valuation_gap, signed=True))
    m3.metric("Gap theo vốn hóa", fmt_pct(regime.market_cap_weighted_gap, signed=True))
    m4.metric("Gap theo chất lượng dữ liệu", fmt_pct(regime.confidence_weighted_gap, signed=True))
    m5.metric("Định giá tương đối", fmt_pct(regime.relative_value_breadth_score, signed=True))

    left, right = st.columns([1, 1.35])
    with left:
        chart = plot_classification_breadth(classification_summary(data))
        if chart is not None:
            st.plotly_chart(chart, use_container_width=True)
    with right:
        chart = plot_valuation_gap(data)
        if chart is not None:
            st.plotly_chart(chart, use_container_width=True)

    with st.expander("Phạm vi phương pháp luận", expanded=True):
        st.markdown(
            """
Mô hình này không tuyên bố định giá toàn bộ thị trường trực tiếp. Nó đánh giá
độ rộng định giá của các ngân hàng niêm yết, sau đó dùng trạng thái định giá
của nhóm ngân hàng như một proxy cho thị trường vì ngân hàng là nhóm cốt lõi
về vốn hóa, thanh khoản và chu kỳ tín dụng tại Việt Nam.

Công thức điểm độ rộng: `Rẻ rõ rệt + 0.5 x Rẻ nhưng rủi ro - Định giá cao`, chia cho số mã hợp lệ.
            """.strip()
        )

    detail_cols = [
        "ticker",
        "period",
        "classification",
        "valuation_gap_pct",
        "market_pb",
        "justified_pb",
        "fair_value_per_share_rim",
        "overall_risk_score",
        "data_quality_flag",
        "relative_valuation_label",
        "market_mispricing_score",
    ]
    detail_cols = [col for col in detail_cols if col in data.columns]
    detail_df = data[detail_cols].copy()
    if "classification" in detail_df.columns:
        detail_df["classification"] = detail_df["classification"].map(_classification_label_vi)

    st.subheader("Bảng chi tiết theo mã")
    st.dataframe(
        detail_df.sort_values("valuation_gap_pct", ascending=True).style.format(
            {
                "valuation_gap_pct": "{:.1%}",
                "market_pb": "{:.2f}x",
                "justified_pb": "{:.2f}x",
                "fair_value_per_share_rim": "{:,.0f}",
                "overall_risk_score": "{:.1f}",
                "market_mispricing_score": "{:.1%}",
            },
            na_rep="n/a",
        ),
        use_container_width=True,
    )


def _render_ticker_detail(data: pd.DataFrame) -> None:
    st.header("Định Giá Từng Mã")
    tickers = sorted(data["ticker"].dropna().astype(str).unique())
    selected = st.selectbox("Chọn mã", tickers, key="bank_valuation_ticker")
    row = data[data["ticker"] == selected].iloc[0]

    st.header(f"Chi Tiết Định Giá {selected}")
    st.subheader(f"Phân loại: {_classification_label_vi(row.get('classification'))}")

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Giá thị trường", f"{row.get('price', float('nan')):,.0f}" if pd.notna(row.get("price")) else "n/a")
    col2.metric(
        "Giá trị hợp lý RIM",
        f"{row.get('fair_value_per_share_rim', float('nan')):,.0f}" if pd.notna(row.get("fair_value_per_share_rim")) else "n/a",
        fmt_pct(row.get("valuation_gap_pct"), signed=True),
    )
    col3.metric("P/B thị trường", f"{row.get('market_pb', float('nan')):.2f}x" if pd.notna(row.get("market_pb")) else "n/a")
    col4.metric("P/B hợp lý", f"{row.get('justified_pb', float('nan')):.2f}x" if pd.notna(row.get("justified_pb")) else "n/a")
    col5.metric("Beta", f"{row.get('beta', float('nan')):.2f}" if pd.notna(row.get("beta")) else "n/a")
    col6.metric("Chất lượng dữ liệu", row.get("data_quality_flag", "n/a"))

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Ảnh Chụp Định Giá")
        st.write(f"**BVPS báo cáo:** {row['book_value_per_share']:,.0f}" if pd.notna(row.get("book_value_per_share")) else "**BVPS báo cáo:** n/a")
        st.write(f"**BVPS điều chỉnh:** {row['adjusted_book_value_per_share']:,.0f}" if pd.notna(row.get("adjusted_book_value_per_share")) else "**BVPS điều chỉnh:** n/a")
        st.write(f"**ROE bền vững:** {row['sustainable_roe'] * 100:.2f}%" if pd.notna(row.get("sustainable_roe")) else "**ROE bền vững:** n/a")
        st.write(f"**Chi phí vốn:** {row['cost_of_equity'] * 100:.2f}%" if pd.notna(row.get("cost_of_equity")) else "**Chi phí vốn:** n/a")
        st.write(f"**Giá trị stress:** {row['stress_value_per_share']:,.0f}" if pd.notna(row.get("stress_value_per_share")) else "**Giá trị stress:** n/a")

        st.subheader("Định Giá Tương Đối")
        st.write(f"**P/B trung vị peer:** {row['peer_median_pb']:.2f}x" if pd.notna(row.get("peer_median_pb")) else "**P/B trung vị peer:** n/a")
        st.write(f"**P/B hợp lý theo ROE:** {row['roe_adjusted_fair_pb']:.2f}x" if pd.notna(row.get("roe_adjusted_fair_pb")) else "**P/B hợp lý theo ROE:** n/a")
        st.write(f"**Chênh lệch định giá tương đối:** {row['market_mispricing_score']:.1%}" if pd.notna(row.get("market_mispricing_score")) else "**Chênh lệch định giá tương đối:** n/a")
        st.write(f"**Nhãn tương đối:** {row.get('relative_valuation_label', 'n/a')}")

    with col_b:
        st.subheader("Điểm Rủi Ro (0-100, thấp hơn là tốt hơn)")
        st.write(f"**Rủi ro chu kỳ tín dụng:** {row.get('credit_cycle_score', float('nan')):.1f}")
        st.write(f"**Rủi ro tài sản bảo đảm:** {row.get('collateral_risk_score', float('nan')):.1f}")
        st.write(f"**Rủi ro chất lượng huy động:** {100 - row.get('funding_quality_score', float('nan')):.1f}")
        st.write(f"**Rủi ro pha loãng vốn:** {row.get('capital_dilution_risk_score', float('nan')):.1f}")
        st.write(f"**Điểm rủi ro tổng hợp:** {row.get('overall_risk_score', float('nan')):.1f}")
        st.write(f"**Xác nhận giá:** {row.get('market_confirmation_label', 'n/a')}")

    if row.get("warnings"):
        st.warning(f"Cảnh báo: {row['warnings']}")
    if row.get("relative_value_warning"):
        st.info(f"Định giá tương đối: {row['relative_value_warning']}")


def _render_ai_analysis(data: pd.DataFrame, ai_provider: str, api_key: str) -> None:
    st.header("AI Data Analysis")
    watchlist = _confirmation_universe(data)
    counts = _classification_counts(data)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Tickers", f"{len(data)}")
    col2.metric("Overvalued", f"{counts['overvalued']}")
    col3.metric("Fair", f"{counts['fair']}")
    col4.metric("Undervalued", f"{counts['under']}")
    col5.metric("AI Universe", f"{len(watchlist)}")

    provider_name = AI_PROVIDER_MAP.get(ai_provider, {}).get("display", ai_provider)
    cache_file = _ai_cache_file(ai_provider)
    tab_current, tab_history, tab_context = st.tabs(["Current Analysis", "History", "Data Context"])

    with tab_current:
        focus_question = st.text_area(
            "Analysis focus",
            value="",
            placeholder="Example: Which fair or undervalued banks are confirmed by price action?",
            height=90,
            key="bank_ai_focus_question",
        )
        result_text = None
        if st.button(f"Run AI Analysis ({provider_name})", type="primary", use_container_width=True, key="bank_ai_run"):
            if not api_key:
                st.error("Missing API key. Enter an API key in the sidebar.")
            else:
                with st.spinner("AI is analyzing valuation, risk and market confirmation data..."):
                    try:
                        result_text = run_ai_analysis(
                            api_key=api_key,
                            provider_key=ai_provider,
                            data=data,
                            ohlcv_source="platform_market_data",
                            focus_question=focus_question,
                        )
                        cache_file.parent.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(result_text, encoding="utf-8")
                        st.success("AI analysis completed.")
                    except Exception as exc:
                        st.error(f"AI API error: {exc}")

        if result_text is None and cache_file.exists():
            st.success("Loaded today's AI analysis from cache.")
            result_text = cache_file.read_text(encoding="utf-8")

        if result_text:
            with st.container(border=True):
                st.markdown(result_text)
            st.download_button(
                "Download AI Analysis",
                data=result_text,
                file_name=cache_file.name,
                mime="text/markdown",
                use_container_width=True,
            )

    with tab_history:
        history_files = list(DATA_LAKE.glob("daily_cache/bank_valuation_ai_*.txt"))
        options = build_history_options(history_files, "bank_valuation_ai", AI_PROVIDER_MAP)
        if not options:
            st.info("No AI analysis history yet.")
        else:
            selected_label = st.selectbox(
                "Select cached analysis",
                options=list(options.keys()),
                index=0,
                key="bank_ai_history_selector",
            )
            selected_path = options[selected_label]
            selected_text = selected_path.read_text(encoding="utf-8")
            with st.container(border=True):
                st.markdown(selected_text)
            st.download_button(
                "Download Selected Analysis",
                data=selected_text,
                file_name=selected_path.name,
                mime="text/markdown",
                use_container_width=True,
            )

    with tab_context:
        display_cols = [
            "ticker",
            "period",
            "price",
            "beta",
            "fair_value_per_share_rim",
            "stress_value_per_share",
            "valuation_gap_pct",
            "classification",
            "overall_risk_score",
            "data_quality_flag",
            "confidence_score",
            "relative_valuation_label",
            "market_mispricing_score",
            "market_close",
            "market_confirmation_score",
            "market_confirmation_label",
            "return_20d",
            "return_60d",
            "volume_ratio_20d",
            "drawdown_60d",
            "warnings",
        ]
        display_cols = [col for col in display_cols if col in data.columns]
        st.dataframe(
            data[display_cols].style.format(
                {
                    "price": "{:,.0f}",
                    "beta": "{:.2f}",
                    "fair_value_per_share_rim": "{:,.0f}",
                    "stress_value_per_share": "{:,.0f}",
                    "valuation_gap_pct": "{:.1%}",
                    "overall_risk_score": "{:.1f}",
                    "confidence_score": "{:.1f}",
                    "market_close": "{:,.0f}",
                    "market_confirmation_score": "{:.1f}",
                    "return_20d": "{:.1%}",
                    "return_60d": "{:.1%}",
                    "volume_ratio_20d": "{:.2f}",
                    "drawdown_60d": "{:.1%}",
                },
                na_rep="n/a",
            ),
            use_container_width=True,
        )


def render():
    st.title("Bank Valuation")
    st.caption(
        "Adjusted Book Value + Sustainable ROE + Residual Income + stress-adjusted fair P/B, "
        "chạy trực tiếp từ BCTC JSON trong data_lake của Quant Platform."
    )

    st.sidebar.header("Bank Valuation")
    force_recompute = st.sidebar.button("Cập nhật / tính lại định giá", key="bank_valuation_force_recompute")
    st.sidebar.divider()
    st.sidebar.header("AI Analysis")
    provider_options = list(AI_PROVIDER_MAP.keys())
    default_provider = "deepseek-v4-pro" if "deepseek-v4-pro" in provider_options else provider_options[0]
    ai_provider = st.sidebar.selectbox(
        "AI Provider",
        options=provider_options,
        index=provider_options.index(default_provider),
        format_func=lambda key: AI_PROVIDER_MAP[key]["display"],
        key="bank_valuation_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "AI API Key (hoặc shortcut 4 số)",
        type="password",
        key="bank_valuation_ai_key",
        placeholder="sk-... hoặc 4 số",
    )
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    try:
        close_prices = load_close_prices()
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()
        return

    volumes = load_volumes()
    price_date = close_prices.index.max().strftime("%Y-%m-%d") if not close_prices.empty else "n/a"
    source_signature = bank_valuation_source_signature()
    data_date = f"{price_date}|{source_signature}"
    cache_key = {
        "cache_version": 2,
        "source_signature": source_signature,
        "price_date": price_date,
        "include_market_confirmation": True,
    }

    with st.spinner("Đang chạy Bank Valuation pipeline từ data_lake..."):
        cached = load_daily_cache("bank_valuation", cache_key, data_date=data_date)
        if cached is not None and not force_recompute:
            valuation_df = cached["valuation_df"]
            ohlcv_rows = cached.get("ohlcv_rows", 0)
            st.caption("Dùng cache cùng ngày (Bank Valuation).")
        else:
            try:
                valuation_df, ohlcv_df = run_bank_valuation_pipeline(close_prices=close_prices, volumes=volumes)
            except Exception as exc:
                st.error(str(exc))
                st.info(
                    "Kiểm tra input tại "
                    f"`{BCTC_JSON_DIR}` hoặc cập nhật bằng `python command/update_bank_valuation_data.py`."
                )
                st.stop()
                return
            ohlcv_rows = len(ohlcv_df)
            save_daily_cache(
                "bank_valuation",
                cache_key,
                {"valuation_df": valuation_df, "ohlcv_rows": ohlcv_rows},
                data_date=data_date,
            )
            st.caption("Đã tạo cache ngày mới (Bank Valuation).")

    if valuation_df.empty:
        st.warning("Bank Valuation không có kết quả hợp lệ.")
        st.stop()
        return

    st.caption(
        f"Giá platform: {price_date} | BCTC feed: {source_signature.split(':', 1)[0]} | "
        f"Kỳ dữ liệu phổ biến: {latest_period(valuation_df)} | "
        f"{len(valuation_df)} ngân hàng | {ohlcv_rows:,} dòng market data nội bộ"
    )

    tab_overview, tab_regime, tab_detail, tab_ai = st.tabs(
        ["Tổng Quan", "Trạng Thái Thị Trường", "Định Giá Từng Mã", "Phân Tích AI"]
    )

    with tab_overview:
        _render_overview(valuation_df)
    with tab_regime:
        _render_market_regime(valuation_df)
    with tab_detail:
        _render_ticker_detail(valuation_df)
    with tab_ai:
        _render_ai_analysis(valuation_df, ai_provider, api_key)
        with st.expander("Raw result columns"):
            st.dataframe(valuation_df, use_container_width=True)
