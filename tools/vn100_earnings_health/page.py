from __future__ import annotations

import json
import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from config import AI_PROVIDER_MAP, ROOT_DIR
from shared.api_key_helper import resolve_api_key as resolve_platform_api_key
from tools.vn100_earnings_health.quant.ai_analysis import (
    PROMPT_PATH,
    cache_path,
    list_cached_reports,
    prepare_ai_payload,
    run_ai_analysis,
)
from tools.vn100_earnings_health.quant.config import CORE_COLUMNS, DISPLAY_CORE_NAMES, OUTPUT_DIR
from tools.vn100_earnings_health.quant.pipeline import run_and_write


CORE_LABELS = {column: DISPLAY_CORE_NAMES.get(column, column) for column in CORE_COLUMNS}
CORE_LABELS["leverage_stress_score"] = "Leverage Stress"
CORE_LABELS["corporate_health_score"] = "Corporate Health"


@st.cache_data(show_spinner=False)
def load_outputs() -> dict[str, pd.DataFrame | dict]:
    if not (OUTPUT_DIR / "company_scores.parquet").exists():
        run_and_write()
    data = {
        "company": pd.read_parquet(OUTPUT_DIR / "company_scores.parquet"),
        "sector": pd.read_parquet(OUTPUT_DIR / "sector_scores.parquet"),
        "vn100": pd.read_parquet(OUTPUT_DIR / "vn100_scores.parquet"),
        "core_matrix": pd.read_parquet(OUTPUT_DIR / "core_consistency_matrix.parquet"),
        "transmission": pd.read_parquet(OUTPUT_DIR / "transmission_matrix.parquet"),
        "pca": pd.read_parquet(OUTPUT_DIR / "pca_factor.parquet"),
        "pca_loadings": pd.read_parquet(OUTPUT_DIR / "pca_loadings.parquet"),
        "alerts": pd.read_parquet(OUTPUT_DIR / "alerts.parquet"),
        "metadata": pd.read_parquet(OUTPUT_DIR / "ticker_metadata.parquet"),
    }
    summary_path = OUTPUT_DIR / "run_summary.json"
    data["summary"] = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return data


def fmt_score(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.1f}"


def fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value) * 100:.1f}%"


def latest_available_period(data: dict) -> str:
    company = data["company"]
    latest_order = company["period_order"].max()
    return company.loc[company["period_order"].eq(latest_order), "period"].iloc[0]


def period_order(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1])


def current_and_previous(company: pd.DataFrame, period: str, mode: str) -> pd.DataFrame:
    current = company[company["period"].eq(period)].copy()
    lag = 4 if mode == "YoY" else 1
    previous_order = period_order(period) - lag
    previous = company[company["period_order"].eq(previous_order)][[
        "ticker",
        "corporate_health_score",
    ]].rename(columns={"corporate_health_score": "previous_health_score"})
    current = current.merge(previous, on="ticker", how="left")
    current["health_change"] = current["corporate_health_score"] - current["previous_health_score"]
    return current


def metric_row(items: list[tuple[str, str, str | None]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, delta) in zip(columns, items):
        column.metric(label, value, delta=delta)


def strip_duplicate_ai_verdict(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    if not lines:
        return markdown_text

    first_section = re.compile(r"^\s*#{0,6}\s*0\.\s*Final Macro Verdict\b", re.IGNORECASE)
    next_section = re.compile(r"^\s*#{0,6}\s*1\.\s+", re.IGNORECASE)
    if not first_section.match(lines[0]):
        return markdown_text

    for idx, line in enumerate(lines[1:], start=1):
        if next_section.match(line):
            return "\n".join(lines[idx:]).lstrip()
    return markdown_text


def render_ai_report(markdown_text: str) -> None:
    st.markdown(strip_duplicate_ai_verdict(markdown_text))


def line_chart(df: pd.DataFrame, x: str, y: list[str], title: str, labels: dict | None = None):
    fig = px.line(df, x=x, y=y, markers=True, title=title, labels=labels or {})
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=45, b=10), legend_title_text="")
    fig.update_xaxes(title_text="")
    st.plotly_chart(fig, width='stretch')


def overview_page(data: dict, mode: str, period: str) -> None:
    vn100 = data["vn100"].copy()
    company = data["company"].copy()
    vn100_view = vn100[vn100["period_order"].le(period_order(period))]
    row = vn100[vn100["period"].eq(period)].iloc[0]
    current = current_and_previous(company, period, mode)

    metric_row(
        [
            ("VN100 Health", fmt_score(row["vn100_health_score"]), None),
            ("Regime", row["regime"], None),
            ("Revenue Breadth", fmt_pct(row["revenue_breadth"]), None),
            ("Profit Breadth", fmt_pct(row["profit_breadth"]), None),
            ("CFO Breadth", fmt_pct(row["cfo_breadth"]), None),
            ("Healthy Growth", fmt_pct(row["healthy_growth_breadth"]), None),
        ]
    )
    metric_row(
        [
            ("WC Stress", fmt_score(row["working_capital_stress_index"]), None),
            ("Leverage Stress", fmt_score(row["leverage_stress_index"]), None),
            ("Sector Diffusion", fmt_pct(row["sector_diffusion_score"]), None),
            ("EW Health", fmt_score(row["equal_weight_corporate_health_score"]), None),
            ("MCW Health", fmt_score(row["market_cap_weight_corporate_health_score"]), None),
            ("Valid Companies", str(int(row["valid_company_count"])), None),
        ]
    )

    chart_cols = st.columns([2, 1])
    with chart_cols[0]:
        line_chart(
            vn100_view,
            "period",
            ["vn100_health_score", "vn100_health_score_market_cap_weighted"],
            "VN100 Health Trend",
            {
                "value": "Score",
                "variable": "Aggregation",
                "vn100_health_score": "Equal-weight",
            },
        )
    with chart_cols[1]:
        diagnosis = json.loads(row["main_diagnosis"]) if isinstance(row["main_diagnosis"], str) else row["main_diagnosis"]
        st.subheader("Diagnosis")
        for item in diagnosis:
            st.write(f"- {item}")

    top_cols = st.columns(2)
    top_positive = current.sort_values("health_change", ascending=False).head(12)
    top_negative = current.sort_values("health_change", ascending=True).head(12)
    with top_cols[0]:
        fig = px.bar(
            top_positive,
            x="health_change",
            y="ticker",
            orientation="h",
            color="sector",
            title="Top Positive Contributors",
            hover_data=["company_name", "corporate_health_score"],
        )
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=45, b=10), yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width='stretch')
    with top_cols[1]:
        fig = px.bar(
            top_negative,
            x="health_change",
            y="ticker",
            orientation="h",
            color="sector",
            title="Top Negative Contributors",
            hover_data=["company_name", "corporate_health_score"],
        )
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=45, b=10), yaxis={"categoryorder": "total descending"})
        st.plotly_chart(fig, width='stretch')


def core_breakdown_page(data: dict, mode: str, period: str) -> None:
    vn100 = data["vn100"].copy()
    vn100 = vn100[vn100["period_order"].le(period_order(period))]
    row = data["vn100"][data["vn100"]["period"].eq(period)].iloc[0]

    core_values = pd.DataFrame(
        {
            "core": [
                "Growth",
                "Profitability",
                "Cash Conversion",
                "Balance Sheet",
                "Capital Allocation",
                "WC Stress",
                "Leverage Stress",
                "Matrix Consistency",
            ],
            "score": [
                row["equal_weight_growth_score"],
                row["equal_weight_profitability_score"],
                row["equal_weight_cash_conversion_score"],
                row["equal_weight_balance_sheet_resilience_score"],
                row["equal_weight_capital_allocation_score"],
                row["equal_weight_working_capital_stress_score"],
                row["equal_weight_leverage_stress_score"],
                row["equal_weight_matrix_consistency_score"],
            ],
            "type": [
                "Health",
                "Health",
                "Health",
                "Health",
                "Health",
                "Stress",
                "Stress",
                "Consistency",
            ],
        }
    )
    fig = px.bar(core_values, x="core", y="score", color="type", title="Core Scores", range_y=[0, 100])
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=45, b=10), xaxis_title="")
    st.plotly_chart(fig, width='stretch')

    trend_cols = [
        "equal_weight_growth_score",
        "equal_weight_profitability_score",
        "equal_weight_cash_conversion_score",
        "equal_weight_balance_sheet_resilience_score",
        "equal_weight_working_capital_stress_score",
        "equal_weight_leverage_stress_score",
    ]
    trend = vn100[["period", *trend_cols]].rename(
        columns={col: col.replace("equal_weight_", "").replace("_score", "").replace("_", " ").title() for col in trend_cols}
    )
    line_chart(trend, "period", list(trend.columns[1:]), "Core Trend")

    latest_company = data["company"][data["company"]["period"].eq(period)]
    table_cols = [
        "ticker",
        "company_name",
        "sector",
        "corporate_health_score",
        "growth_score",
        "cash_conversion_score",
        "working_capital_stress_score",
        "leverage_stress_score",
        "primary_flag",
    ]
    st.dataframe(
        latest_company[table_cols].sort_values("corporate_health_score", ascending=False),
        width='stretch',
        hide_index=True,
    )


def matrix_page(data: dict, period: str) -> None:
    matrix = data["core_matrix"]
    period_matrix = matrix[matrix["period"].eq(period)]
    if period_matrix.empty:
        st.warning("No matrix data for the latest snapshot.")
        return
    heat = period_matrix.pivot(index="left_core", columns="right_core", values="correlation")
    heat = heat.rename(index=CORE_LABELS, columns=CORE_LABELS)
    fig = px.imshow(
        heat,
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        text_auto=".2f",
        title="Core Consistency Matrix",
    )
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=45, b=10))
    st.plotly_chart(fig, width='stretch')

    company = data["company"]
    tickers = sorted(company["ticker"].dropna().unique())
    selected = st.selectbox("Ticker", tickers, index=tickers.index("HPG") if "HPG" in tickers else 0)
    transmission = data["transmission"]
    flow = transmission[(transmission["ticker"].eq(selected)) & (transmission["period"].eq(period))]
    if flow.empty:
        st.info("No transmission data for the selected ticker.")
    else:
        st.dataframe(
            flow[["link", "meaning", "score", "status", "severity"]],
            width='stretch',
            hide_index=True,
        )

    diagnostics = period_matrix[
        (period_matrix["left_core"] != period_matrix["right_core"])
        & (period_matrix["severity"].isin(["High", "Medium"]))
    ][["left_core", "right_core", "correlation", "diagnostic_label", "severity"]].copy()
    diagnostics["left_core"] = diagnostics["left_core"].map(CORE_LABELS)
    diagnostics["right_core"] = diagnostics["right_core"].map(CORE_LABELS)
    st.dataframe(diagnostics.sort_values(["severity", "correlation"]), width='stretch', hide_index=True)


def sector_page(data: dict, period: str) -> None:
    sector = data["sector"]
    latest = sector[sector["period"].eq(period)].copy()
    if latest.empty:
        st.warning("No sector data for the latest snapshot.")
        return
    heat_cols = [
        "sector_growth_score",
        "sector_profitability_score",
        "sector_cash_conversion_score",
        "sector_working_capital_stress",
        "sector_leverage_stress",
        "sector_health_score",
    ]
    heat = latest.set_index("sector")[heat_cols].rename(
        columns={
            "sector_growth_score": "Growth",
            "sector_profitability_score": "Profit",
            "sector_cash_conversion_score": "Cashflow",
            "sector_working_capital_stress": "WC Stress",
            "sector_leverage_stress": "Leverage",
            "sector_health_score": "Health",
        }
    )
    fig = px.imshow(heat, color_continuous_scale="RdYlGn", zmin=0, zmax=100, text_auto=".0f", title="Sector x Core")
    fig.update_layout(height=650, margin=dict(l=10, r=10, t=45, b=10))
    st.plotly_chart(fig, width='stretch')

    cols = st.columns(2)
    with cols[0]:
        fig = px.bar(
            latest.sort_values("sector_health_score"),
            x="sector_health_score",
            y="sector",
            orientation="h",
            color="sector_diffusion_label",
            title="Sector Health",
        )
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=45, b=10), yaxis_title="")
        st.plotly_chart(fig, width='stretch')
    with cols[1]:
        st.dataframe(
            latest[
                [
                    "sector",
                    "company_count",
                    "sector_health_score",
                    "sector_growth_score",
                    "sector_cash_conversion_score",
                    "sector_working_capital_stress",
                    "sector_leverage_stress",
                    "sector_diffusion_label",
                ]
            ].sort_values("sector_health_score", ascending=False),
            width='stretch',
            hide_index=True,
        )


def company_page(data: dict, mode: str, period: str) -> None:
    company = data["company"]
    tickers = sorted(company["ticker"].dropna().unique())
    selected = st.selectbox("Company", tickers, index=tickers.index("HPG") if "HPG" in tickers else 0)
    sub = company[company["ticker"].eq(selected)].sort_values("period_order")
    current = sub[sub["period"].eq(period)]
    if current.empty:
        current = sub.tail(1)
    row = current.iloc[0]

    metric_row(
        [
            ("Health", fmt_score(row["corporate_health_score"]), None),
            ("Regime Sector", row.get("sector_diffusion_label", "NA"), None),
            ("Growth", fmt_score(row["growth_score"]), None),
            ("Cash Conversion", fmt_score(row["cash_conversion_score"]), None),
            ("WC Stress", fmt_score(row["working_capital_stress_score"]), None),
            ("Leverage Stress", fmt_score(row["leverage_stress_score"]), None),
        ]
    )

    flags = row.get("diagnostic_flags", [])
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except Exception:
            flags = [flags]
    if flags:
        st.subheader("Diagnostic Flags")
        st.write(" ".join([f"`{flag}`" for flag in flags]))

    cols = st.columns([1, 1])
    with cols[0]:
        core_df = pd.DataFrame(
            {
                "core": [
                    "Growth",
                    "Profitability",
                    "Cash Conversion",
                    "Balance Sheet",
                    "Capital Allocation",
                    "WC Stress",
                    "Leverage Stress",
                    "Matrix Consistency",
                ],
                "score": [
                    row["growth_score"],
                    row["profitability_score"],
                    row["cash_conversion_score"],
                    row["balance_sheet_resilience_score"],
                    row["capital_allocation_score"],
                    row["working_capital_stress_score"],
                    row["leverage_stress_score"],
                    row["matrix_consistency_score"],
                ],
            }
        )
        fig = px.bar(core_df, x="core", y="score", range_y=[0, 100], title=f"{selected} Core Scores")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=45, b=10), xaxis_title="")
        st.plotly_chart(fig, width='stretch')
    with cols[1]:
        trend_cols = [
            "corporate_health_score",
            "growth_score",
            "cash_conversion_score",
            "working_capital_stress_score",
            "leverage_stress_score",
        ]
        trend = sub[["period", *trend_cols]].rename(columns={col: CORE_LABELS.get(col, col) for col in trend_cols})
        line_chart(trend, "period", list(trend.columns[1:]), f"{selected} Trend")

    metric_cols = [
        "ttm_revenue_yoy",
        "ttm_net_profit_yoy",
        "ttm_cfo_yoy",
        "gross_margin",
        "cfo_to_net_profit",
        "receivables_growth_spread",
        "inventory_growth_spread",
        "debt_to_equity",
        "interest_coverage",
        "sector_health_percentile",
        "historical_health_zscore",
    ]
    st.dataframe(sub[metric_cols].tail(12), width='stretch', hide_index=True)

    flow = data["transmission"][(data["transmission"]["ticker"].eq(selected)) & (data["transmission"]["period"].eq(row["period"]))]
    st.dataframe(flow[["link", "score", "status", "severity"]], width='stretch', hide_index=True)


def advanced_page(data: dict) -> None:
    pca = data["pca"]
    fig = px.line(pca, x="period", y="common_health_factor", markers=True, title="Common Health Factor")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=45, b=10))
    fig.update_xaxes(title_text="")
    st.plotly_chart(fig, width='stretch')

    cols = st.columns(2)
    with cols[0]:
        loadings = data["pca_loadings"].copy()
        loadings["core"] = loadings["core"].map(CORE_LABELS).fillna(loadings["core"])
        fig = px.bar(loadings, x="core", y="pc1_loading", title="PC1 Loadings")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=45, b=10), xaxis_title="")
        st.plotly_chart(fig, width='stretch')
    with cols[1]:
        st.subheader("Alerts")
        alerts = data["alerts"].drop(columns=["period"], errors="ignore")
        st.dataframe(alerts, width='stretch', hide_index=True)

    output_files = pd.DataFrame({"file": sorted(path.name for path in OUTPUT_DIR.iterdir() if path.is_file())})
    st.subheader("Output Files")
    st.dataframe(output_files, width='stretch', hide_index=True)


def ai_interpretation_page(data: dict, mode: str, ai_provider: str, api_key: str) -> None:
    st.subheader("AI Interpretation")
    try:
        payload = prepare_ai_payload(data, mode)
        current_cache = cache_path(ai_provider, mode, str(payload["period"]))
    except Exception as exc:
        st.error(f"Cannot prepare AI payload: {exc}")
        return

    with st.container(border=True):
        st.markdown("#### Final Macro Verdict")
        st.markdown(f"**{payload['final_verdict']}**")
        st.write(payload["final_macro_read"])
        cols = st.columns(4)
        cols[0].metric("Confidence", payload["final_confidence"])
        cols[1].metric("Accounting Recovery", payload["accounting_recovery_read"])
        cols[2].metric("Cash-Confirmed Recovery", payload["cash_confirmed_recovery_read"])
        cols[3].metric("Sector Diffusion", payload["sector_diffusion_read"])
        st.caption(f"Systemic stress: {payload['systemic_stress_read']} · Analytical stance: {payload['final_stance']}")
        st.markdown(f"**Sector leadership:** {payload['sector_leadership_read']}")
        st.markdown(f"**Big-cap read:** {payload['big_cap_read']}")
        with st.expander("Sector Leadership & Big-Cap Details", expanded=False):
            st.markdown("**Top sectors by current health**")
            st.markdown(payload["top_sector_leaders"])
            st.markdown("**Positive YoY sector movers used in diffusion score**")
            st.markdown(payload["positive_sector_movers"])
            st.markdown("**Large-cap confirmers**")
            st.markdown(payload["large_cap_confirmers"])
            st.markdown("**Large-cap drags**")
            st.markdown(payload["large_cap_drags"])
        with st.expander("Verdict Evidence"):
            st.markdown(payload["final_evidence"])
        with st.expander("What To Watch Next"):
            st.markdown(payload["watch_next"])

    tab_current, tab_history, tab_prompt = st.tabs(["Current Analysis", "Cached Analyses", "Prompt"])

    with tab_current:
        if current_cache.exists():
            st.info("Loaded cached AI analysis for the latest snapshot.")
            with st.container(border=True):
                render_ai_report(current_cache.read_text(encoding="utf-8"))
            try:
                from shared.github_sync import render_sync_button

                render_sync_button(current_cache, key_suffix=f"vn100_earnings_health_{mode.lower()}")
            except Exception:
                pass
            if st.button("Run Again", type="secondary", key=f"vn100_run_again_{mode.lower()}"):
                current_cache.unlink(missing_ok=True)
                st.rerun()
        else:
            st.write("AI will read the latest generated outputs and produce a structured Vietnamese interpretation.")
            if st.button(
                f"Run AI Analysis ({AI_PROVIDER_MAP[ai_provider]['display']})",
                type="primary",
                width="stretch",
            ):
                if not api_key:
                    st.error("Missing API key. Enter it in the sidebar or set a provider environment variable.")
                    return
                with st.spinner("AI is reading the VN100 Corporate Health outputs"):
                    try:
                        result_text, written_path = run_ai_analysis(
                            data,
                            provider=ai_provider,
                            api_key=api_key,
                            mode=mode,
                        )
                        st.success(f"Analysis saved to {written_path}")
                        with st.container(border=True):
                            render_ai_report(result_text)
                        try:
                            from shared.github_sync import render_sync_button

                            render_sync_button(written_path, key_suffix=f"vn100_earnings_health_{mode.lower()}_new")
                        except Exception:
                            pass
                    except Exception as exc:
                        st.error(f"AI request failed: {exc}")

        with st.expander("Context Preview"):
            preview = {
                k: v
                for k, v in payload.items()
                if not k.endswith("_table") and k not in {"period", "comparison_lag_order"}
            }
            st.json(preview)

    with tab_history:
        caches = list_cached_reports()
        if not caches:
            st.info("No cached AI analyses yet.")
        else:
            options = {}
            for idx, path in enumerate(caches, start=1):
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                options[f"{modified} - {path.name}"] = path
            selected = st.selectbox("Cached file", list(options.keys()), key="vn100_ai_history")
            with st.container(border=True):
                render_ai_report(options[selected].read_text(encoding="utf-8"))

    with tab_prompt:
        if PROMPT_PATH.exists():
            st.code(PROMPT_PATH.read_text(encoding="utf-8"), language="markdown")
        else:
            st.warning(f"Prompt file does not exist: {PROMPT_PATH}")


def _period_options(data: dict) -> list[str]:
    periods = (
        data["vn100"][["period", "period_order"]]
        .drop_duplicates()
        .sort_values("period_order")["period"]
        .astype(str)
        .tolist()
    )
    return periods


def render() -> None:
    data = load_outputs()
    summary = data["summary"]
    st.title("VN100 Corporate Health Monitor")
    st.caption(
        "Bottom-up financial statement monitor for VN100: growth quality, cash conversion, "
        "working-capital stress, leverage stress, sector diffusion, and matrix diagnostics."
    )

    with st.sidebar:
        st.header("VN100 Corporate Health")
        mode = st.segmented_control("Mode", ["YoY", "QoQ"], default="YoY", key="vn100_compare_mode")
        periods = _period_options(data)
        latest_period = latest_available_period(data)
        period = st.selectbox(
            "Snapshot period",
            periods,
            index=periods.index(latest_period) if latest_period in periods else len(periods) - 1,
            key="vn100_period",
        )
        page = st.radio(
            "View",
            [
                "VN100 Health Overview",
                "Core Health Breakdown",
                "Matrix & Correlation Diagnostics",
                "Sector Diffusion Map",
                "Company Drilldown",
                "Advanced Quant & Alerts",
                "AI Interpretation",
            ],
            key="vn100_view",
        )
        st.divider()
        st.header("AI Analysis")
        ai_options = list(AI_PROVIDER_MAP.keys())
        default_ai_provider = "deepseek-v4-pro" if "deepseek-v4-pro" in ai_options else ai_options[0]
        ai_provider = st.selectbox(
            "Model",
            options=ai_options,
            format_func=lambda key: AI_PROVIDER_MAP[key]["display"],
            index=ai_options.index(default_ai_provider) if default_ai_provider in ai_options else 0,
            key="vn100_ai_provider",
        )
        api_key_raw = st.text_input(
            "API Key (hoặc shortcut 4 số)",
            type="password",
            placeholder="sk-... hoặc 4 số",
            key="vn100_api_key",
        )
        api_key, api_key_msg, api_key_err = resolve_platform_api_key(api_key_raw, ai_provider)
        if api_key_err:
            st.error(api_key_msg)
        elif api_key_msg:
            st.success(api_key_msg)

        if st.button("Rebuild Outputs", key="vn100_rebuild_outputs"):
            load_outputs.clear()
            with st.spinner("Running pipeline"):
                run_and_write()
            st.rerun()
        if st.button("Clear UI Cache", key="vn100_clear_ui_cache"):
            load_outputs.clear()
            st.rerun()
        st.caption(f"Tickers: {summary.get('tickers', 'NA')}")
        st.caption(f"Outputs: `{OUTPUT_DIR}`")

    if page == "VN100 Health Overview":
        overview_page(data, mode, period)
    elif page == "Core Health Breakdown":
        core_breakdown_page(data, mode, period)
    elif page == "Matrix & Correlation Diagnostics":
        matrix_page(data, period)
    elif page == "Sector Diffusion Map":
        sector_page(data, period)
    elif page == "Company Drilldown":
        company_page(data, mode, period)
    elif page == "Advanced Quant & Alerts":
        advanced_page(data)
    else:
        ai_interpretation_page(data, mode, ai_provider, api_key)


if __name__ == "__main__":
    render()
