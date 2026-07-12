"""Streamlit dashboard for Vietnam bank versus real-estate credit spreads."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from config import AI_PROVIDER_MAP, DATA_LAKE, ROOT_DIR
from shared.api_key_helper import resolve_api_key
from shared.history_selector import build_history_options
from shared.page_layout import render_signal_card
from tools.credit_spread.ai_analysis import (
    CACHE_PREFIX,
    build_credit_spread_snapshot,
    build_structured_context,
    cache_path,
    read_cached_analysis,
    run_ai_analysis,
    write_cached_analysis,
)
from tools.credit_spread.quant.metrics import (
    calculate_benchmark_spreads,
    calculate_credit_spread,
    load_aggregated_yields,
    load_government_yields,
    load_issuance_data,
)
from tools.credit_spread.ui.charts import plot_latest_benchmark, plot_yields_and_spread


DATA_DIR = DATA_LAKE / "credit_spread"
ISSUANCE_PATH = DATA_DIR / "vbma_corp_bond_issuance_detail.csv"
CORPORATE_YIELDS_PATH = DATA_DIR / "vbma_corp_bond_yields.csv"
GOVERNMENT_YIELDS_PATH = DATA_DIR / "bond_yields_vn.csv"
HANDBOOK_PATH = ROOT_DIR / "docs" / "credit_spread_handbook.md"

BUCKET_LABELS = {
    "<=3Y": "Đến 3 năm",
    "3Y_5Y": "Trên 3 đến 5 năm",
    ">5Y": "Trên 5 năm",
}
WEIGHTING_LABELS = {
    "equal": "Bình quân mỗi đợt phát hành",
    "issue_value": "Theo giá trị phát hành",
}
DIRECTION_LABELS = {
    "WIDENING": "Đang nới rộng",
    "NARROWING": "Đang co hẹp",
    "UNCHANGED": "Không đổi",
    "N/A": "Chưa có kỳ trước",
}


def _file_signature(paths: tuple[Path, ...]) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)


@st.cache_data(show_spinner=False)
def _load_bundle(signature: tuple[tuple[str, int, int], ...]):
    del signature
    return (
        load_issuance_data(ISSUANCE_PATH),
        load_aggregated_yields(CORPORATE_YIELDS_PATH),
        load_government_yields(GOVERNMENT_YIELDS_PATH),
    )


def _format_date(value) -> str:
    return pd.Timestamp(value).strftime("%d/%m/%Y")


def _direction_tone(direction: str) -> str:
    return {
        "WIDENING": "danger",
        "NARROWING": "positive",
        "UNCHANGED": "neutral",
        "N/A": "neutral",
    }.get(direction, "neutral")


def _render_header() -> None:
    title_col, handbook_col = st.columns([5, 1])
    with title_col:
        st.title("Credit Spread: Bank vs Bất động sản")
        st.caption(
            "Lãi suất phát hành trái phiếu doanh nghiệp theo kỳ báo cáo VBMA · "
            "spread có dấu = Bank - BĐS · risk premium = BĐS - Bank"
        )
    with handbook_col:
        st.write("")
        if HANDBOOK_PATH.exists():
            st.download_button(
                "Tải phương pháp",
                data=HANDBOOK_PATH.read_text(encoding="utf-8"),
                file_name=HANDBOOK_PATH.name,
                mime="text/markdown",
                width="stretch",
            )


def render() -> None:
    _render_header()

    paths = (ISSUANCE_PATH, CORPORATE_YIELDS_PATH, GOVERNMENT_YIELDS_PATH)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        st.error("Thiếu dữ liệu Credit Spread:\n- " + "\n- ".join(missing))
        st.code("python command/update_credit_spread_data.py")
        return

    try:
        issuance, corporate_yields, government_yields = _load_bundle(_file_signature(paths))
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"Không thể đọc dữ liệu Credit Spread: {exc}")
        return

    target = issuance.loc[issuance["sector"].isin(["bank", "real_estate"])]
    min_date = target["report_date"].min().date()
    max_date = target["report_date"].max().date()
    available_buckets = [bucket for bucket in BUCKET_LABELS if bucket in set(target["maturity_bucket"].dropna())]

    st.sidebar.markdown("### Bộ lọc Credit Spread")
    date_range = st.sidebar.date_input(
        "Khoảng báo cáo",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key="credit_spread_date_range",
    )
    selected_buckets = st.sidebar.multiselect(
        "Kỳ hạn phát hành",
        options=available_buckets,
        default=available_buckets,
        format_func=lambda item: BUCKET_LABELS[item],
        key="credit_spread_maturity",
    )
    weighting = st.sidebar.radio(
        "Phương pháp bình quân",
        options=list(WEIGHTING_LABELS),
        format_func=lambda item: WEIGHTING_LABELS[item],
        horizontal=False,
        key="credit_spread_weighting",
    )
    st.sidebar.divider()
    st.sidebar.markdown("### AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "Model AI",
        options=list(AI_PROVIDER_MAP),
        format_func=lambda key: AI_PROVIDER_MAP[key]["display"],
        key="credit_spread_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key hoặc shortcut 4 số",
        type="password",
        key="credit_spread_api_key",
    )
    api_key, api_key_message, api_key_error = resolve_api_key(api_key_raw, ai_provider)
    if api_key_error:
        st.sidebar.error(api_key_message)
    elif api_key_message:
        st.sidebar.success(api_key_message)

    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range

    if not selected_buckets:
        st.warning("Chọn ít nhất một nhóm kỳ hạn để tính spread.")
        return

    spread = calculate_credit_spread(
        issuance,
        start_date=start_date,
        end_date=end_date,
        maturity_buckets=selected_buckets,
        weighting=weighting,
    )
    if spread.empty:
        st.warning("Không có kỳ báo cáo nào đủ coupon hợp lệ cho cả Bank và BĐS trong bộ lọc này.")
        return

    latest = spread.iloc[-1]
    latest_date = spread.index[-1]
    direction = str(latest["direction"])
    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_signal_card("Kỳ gần nhất", _format_date(latest_date), tone="info")
    with metric_cols[1]:
        render_signal_card("Bank yield", f"{latest['bank_yield_pct']:.2f}%", tone="info")
    with metric_cols[2]:
        render_signal_card("BĐS yield", f"{latest['real_estate_yield_pct']:.2f}%", tone="warning")
    with metric_cols[3]:
        render_signal_card(
            "Risk premium BĐS",
            f"{latest['risk_premium_bps']:.0f} bps",
            tone="danger" if latest["risk_premium_bps"] > 0 else "positive",
            caption=f"Bank - BĐS: {latest['signed_spread_pct']:+.2f} điểm %",
        )
    with metric_cols[4]:
        render_signal_card(
            "Xu hướng kỳ gần nhất",
            DIRECTION_LABELS.get(direction, direction),
            tone=_direction_tone(direction),
            caption=f"Thay đổi: {latest['spread_change_bps']:+.0f} bps" if pd.notna(latest["spread_change_bps"]) else None,
        )

    st.caption(
        f"{len(spread)} kỳ matched · mẫu kỳ gần nhất: "
        f"{int(latest['bank_issuance_count'])} Bank / {int(latest['real_estate_issuance_count'])} BĐS · "
        f"phương pháp: {WEIGHTING_LABELS[weighting].lower()}"
    )

    canonical_snapshot = build_credit_spread_snapshot(issuance)

    tab_spread, tab_benchmark, tab_issuance, tab_quality, tab_ai = st.tabs(
        ["Spread", "TPCP", "Phát hành", "Dữ liệu", "AI"]
    )

    with tab_spread:
        st.plotly_chart(plot_yields_and_spread(spread), width="stretch")
        table = spread.reset_index().copy()
        table["report_date"] = table["report_date"].dt.strftime("%d/%m/%Y")
        table["direction"] = table["direction"].map(DIRECTION_LABELS).fillna(table["direction"])
        table = table.rename(
            columns={
                "report_date": "Kỳ báo cáo",
                "bank_yield_pct": "Bank (%)",
                "real_estate_yield_pct": "BĐS (%)",
                "signed_spread_pct": "Bank - BĐS (điểm %)",
                "risk_premium_bps": "BĐS - Bank (bps)",
                "spread_change_bps": "Thay đổi (bps)",
                "spread_return_pct": "Return (%)",
                "direction": "Xu hướng",
                "bank_issuance_count": "Số đợt Bank",
                "real_estate_issuance_count": "Số đợt BĐS",
            }
        )
        table[["Bank (%)", "BĐS (%)", "Bank - BĐS (điểm %)"]] = table[
            ["Bank (%)", "BĐS (%)", "Bank - BĐS (điểm %)"]
        ].round(2)
        table[["BĐS - Bank (bps)", "Thay đổi (bps)"]] = table[
            ["BĐS - Bank (bps)", "Thay đổi (bps)"]
        ].round(0)
        table["Return (%)"] = table["Return (%)"].round(1)
        display_columns = [
            "Kỳ báo cáo", "Bank (%)", "BĐS (%)", "Bank - BĐS (điểm %)",
            "BĐS - Bank (bps)", "Thay đổi (bps)", "Return (%)", "Xu hướng",
            "Số đợt Bank", "Số đợt BĐS",
        ]
        st.dataframe(table[display_columns].sort_index(ascending=False), width="stretch", hide_index=True)

    with tab_benchmark:
        benchmark = calculate_benchmark_spreads(corporate_yields, government_yields)
        benchmark = benchmark.loc[
            benchmark["maturity_bucket"].isin(selected_buckets)
            & benchmark["report_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
        ].dropna(subset=["government_yield_pct"])
        if benchmark.empty:
            st.info("Không có quan sát TPCP prior-date phù hợp trong phạm vi tối đa 21 ngày.")
        else:
            latest_by_group = (
                benchmark.sort_values("report_date")
                .groupby(["sector", "maturity_bucket"], observed=True, as_index=False)
                .tail(1)
            )
            st.plotly_chart(plot_latest_benchmark(latest_by_group), width="stretch")
            benchmark_table = latest_by_group.copy()
            benchmark_table["report_date"] = benchmark_table["report_date"].dt.strftime("%d/%m/%Y")
            benchmark_table["government_date"] = benchmark_table["government_date"].dt.strftime("%d/%m/%Y")
            benchmark_table["sector"] = benchmark_table["sector"].map({"bank": "Bank", "real_estate": "Bất động sản"})
            benchmark_table["maturity_bucket"] = benchmark_table["maturity_bucket"].map(BUCKET_LABELS)
            benchmark_table[["yield_avg_pct", "government_yield_pct"]] = benchmark_table[
                ["yield_avg_pct", "government_yield_pct"]
            ].round(2)
            benchmark_table["government_spread_bps"] = benchmark_table["government_spread_bps"].round(0)
            st.dataframe(
                benchmark_table.rename(
                    columns={
                        "report_date": "Kỳ DN",
                        "sector": "Ngành",
                        "maturity_bucket": "Kỳ hạn DN",
                        "yield_avg_pct": "Lợi suất DN (%)",
                        "government_tenor": "Tenor TPCP",
                        "government_date": "Ngày TPCP",
                        "government_yield_pct": "Lợi suất TPCP (%)",
                        "government_spread_bps": "Spread/TPCP (bps)",
                    }
                )[[
                    "Kỳ DN", "Ngành", "Kỳ hạn DN", "Lợi suất DN (%)", "Tenor TPCP",
                    "Ngày TPCP", "Lợi suất TPCP (%)", "Spread/TPCP (bps)",
                ]],
                width="stretch",
                hide_index=True,
            )
            st.caption("Proxy kỳ hạn: ≤3Y → TPCP 3Y; 3-5Y → TPCP 5Y; >5Y → TPCP 10Y. Chỉ dùng quan sát TPCP cùng ngày hoặc trước đó.")

    with tab_issuance:
        detail = issuance.loc[
            issuance["sector"].isin(["bank", "real_estate"])
            & issuance["report_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
            & issuance["maturity_bucket"].isin(selected_buckets)
        ].copy()
        detail["sector"] = detail["sector"].map({"bank": "Bank", "real_estate": "Bất động sản"})
        detail["report_date"] = detail["report_date"].dt.strftime("%d/%m/%Y")
        columns = [
            "report_date", "bond_code", "issuer_name", "sector", "coupon_rate_pct",
            "issue_value_bn_vnd", "tenor_years", "maturity_bucket", "coupon_text",
        ]
        columns = [column for column in columns if column in detail.columns]
        for column, digits in (("coupon_rate_pct", 2), ("issue_value_bn_vnd", 1), ("tenor_years", 1)):
            if column in detail.columns:
                detail[column] = detail[column].round(digits)
        st.dataframe(detail[columns].sort_index(ascending=False), width="stretch", hide_index=True)

    with tab_quality:
        quality = target.copy()
        quality["coupon_valid"] = quality["coupon_rate_pct"].notna()
        summary = (
            quality.groupby("sector", observed=True)
            .agg(
                total_issues=("sector", "size"),
                fixed_coupon_issues=("coupon_valid", "sum"),
                report_dates=("report_date", "nunique"),
                first_report=("report_date", "min"),
                last_report=("report_date", "max"),
            )
            .reset_index()
        )
        summary["coupon_coverage_pct"] = summary["fixed_coupon_issues"] / summary["total_issues"] * 100.0
        summary["coupon_coverage_pct"] = summary["coupon_coverage_pct"].round(1)
        summary["sector"] = summary["sector"].map({"bank": "Bank", "real_estate": "Bất động sản"})
        summary["first_report"] = summary["first_report"].dt.strftime("%d/%m/%Y")
        summary["last_report"] = summary["last_report"].dt.strftime("%d/%m/%Y")
        st.dataframe(
            summary.rename(
                columns={
                    "sector": "Ngành",
                    "total_issues": "Tổng đợt",
                    "fixed_coupon_issues": "Coupon số hợp lệ",
                    "coupon_coverage_pct": "Coverage coupon (%)",
                    "report_dates": "Số kỳ báo cáo",
                    "first_report": "Kỳ đầu",
                    "last_report": "Kỳ cuối",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.warning(
            "Các trái phiếu lãi suất thả nổi không quy đổi được sang coupon cố định bị loại. "
            "Spread có thể thay đổi mạnh khi số đợt phát hành ít hoặc cơ cấu kỳ hạn giữa hai ngành khác nhau."
        )

    with tab_ai:
        provider_name = AI_PROVIDER_MAP[ai_provider]["display"]
        current_cache = cache_path(ai_provider)
        current_report = read_cached_analysis(current_cache, canonical_snapshot["date"])
        ai_current, ai_history, ai_context = st.tabs(["Hiện tại", "Lịch sử", "Context"])

        with ai_current:
            action_label = f"Phân tích lại với {provider_name}" if current_report else f"Phân tích với {provider_name}"
            if st.button(
                action_label,
                type="primary",
                width="stretch",
                key="credit_spread_ai_run",
            ):
                if not api_key:
                    st.error("Nhập API key ở sidebar để chạy AI Analysis.")
                else:
                    with st.spinner("AI đang phân tích credit spread Bank và BĐS..."):
                        try:
                            current_report = run_ai_analysis(
                                snapshot=canonical_snapshot,
                                provider_key=ai_provider,
                                api_key=api_key,
                            )
                            write_cached_analysis(current_cache, current_report)
                            st.success("Đã hoàn tất AI Analysis và cập nhật cache dùng chung với AI CIO.")
                        except (OSError, ValueError, RuntimeError) as exc:
                            st.error(f"Không thể chạy AI Analysis: {exc}")
                        except Exception as exc:
                            st.error(f"Lỗi API AI: {exc}")

            if current_report:
                with st.container(border=True):
                    st.markdown(current_report)
                st.download_button(
                    "Tải AI Analysis",
                    data=current_report,
                    file_name=current_cache.name,
                    mime="text/markdown",
                    width="stretch",
                )
            else:
                st.info("Chưa có AI Analysis theo methodology hiện tại cho model đã chọn.")

        with ai_history:
            history_files = list((DATA_LAKE / "daily_cache").glob(f"{CACHE_PREFIX}_*.txt"))
            history_options = build_history_options(history_files, CACHE_PREFIX, AI_PROVIDER_MAP)
            if not history_options:
                st.info("Chưa có lịch sử AI Analysis.")
            else:
                selected_label = st.selectbox(
                    "Ngày và model",
                    options=list(history_options),
                    key="credit_spread_ai_history",
                )
                selected_path = history_options[selected_label]
                selected_report = read_cached_analysis(selected_path)
                if selected_report:
                    with st.container(border=True):
                        st.markdown(selected_report)
                else:
                    st.warning("Cache được chọn thuộc methodology cũ và không được sử dụng.")

        with ai_context:
            context_text = build_structured_context(canonical_snapshot)
            st.code(context_text, language="text")
            st.download_button(
                "Tải structured context",
                data=context_text,
                file_name=f"credit_spread_context_{canonical_snapshot['data_date_iso']}.txt",
                mime="text/plain",
                width="stretch",
            )


if __name__ == "__main__":
    st.set_page_config(page_title="Credit Spread", layout="wide")
    render()
