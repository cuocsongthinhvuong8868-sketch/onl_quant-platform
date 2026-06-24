"""Streamlit UI for ABM market simulation and margin cascade monitoring."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from config import DATA_LAKE
except Exception:
    DATA_LAKE = Path(__file__).resolve().parents[2] / "data_lake"


REQUIRED_TABLES = {
    "abm_behavioral_state": "Behavioral state",
    "abm_stress_test": "Stress test",
    "abm_alert": "Alert state",
}
OPTIONAL_TABLES = {
    "abm_latent_state": "Latent state",
    "abm_validation": "Validation",
}
SCENARIO_TABLE = "abm_scenario_grid"


def _load_csv(table: str) -> pd.DataFrame:
    path = DATA_LAKE / f"{table}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        st.error(f"Cannot read {path.name}: {exc}")
        return pd.DataFrame()
    if "as_of_date" in df.columns:
        df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce")
        df = df.dropna(subset=["as_of_date"]).sort_values("as_of_date")
    return df


def _merge_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for table, df in frames.items():
        if df.empty or "as_of_date" not in df.columns:
            continue
        suffix = "_" + table.replace("abm_", "")
        merged = df.copy() if merged is None else merged.merge(
            df,
            on="as_of_date",
            how="outer",
            suffixes=("", suffix),
        )
    if merged is None:
        return pd.DataFrame()
    return merged.sort_values("as_of_date").reset_index(drop=True)


def _first(row: pd.Series, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return default


def _float(row: pd.Series, *names: str, default: float | None = None) -> float | None:
    value = _first(row, *names, default=default)
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100.0:.{digits}f}%"


def _fmt_num(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def _boolish(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


def _regime_color(regime: str) -> str:
    return {
        "CASCADE_WARNING": "#c1121f",
        "CASCADE_RISK": "#c1121f",
        "LEVERAGE_STRESS": "#f77f00",
        "STRESS_RISING": "#f77f00",
        "FRAGILITY_BUILDUP": "#b7791f",
        "POST_SHOCK_STRESS": "#7b2cbf",
        "MARGIN_BUILDUP": "#2f6f9f",
        "BUBBLE_BUILDING": "#2f6f9f",
        "PANIC_OVERSOLD": "#7a9e35",
        "SAFE_VALUE": "#2a9d8f",
    }.get(str(regime or "").upper(), "#6c757d")


def _warning_level_color(level: str, score: float | None = None) -> str:
    level_key = str(level or "").upper()
    if level_key == "RED":
        return "#c1121f"
    if level_key == "ORANGE":
        return "#f77f00"
    if level_key == "YELLOW":
        return "#b7791f"
    if level_key == "GREEN":
        return "#2a9d8f"
    if score is not None:
        if score >= 75:
            return "#c1121f"
        if score >= 60:
            return "#f77f00"
        if score >= 45:
            return "#b7791f"
    return "#6c757d"


def _format_warning_basis(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return "N/A"
    parts = [part.strip().replace("_", " ").capitalize() for part in text.split(",") if part.strip()]
    return "; ".join(parts) if parts else "N/A"


def _agent_mix_frame(row: pd.Series) -> pd.DataFrame:
    values = {
        "Fundamental": _float(row, "pct_fundamental", default=0.0) or 0.0,
        "Momentum": _float(row, "pct_momentum", default=0.0) or 0.0,
        "Foreign": _float(row, "pct_foreign", default=0.0) or 0.0,
        "Leveraged": _float(row, "pct_leveraged", default=0.0) or 0.0,
    }
    noise = _float(row, "pct_noise")
    if noise is None:
        noise = max(0.0, 1.0 - sum(values.values()))
    values["Noise"] = noise
    return pd.DataFrame({"agent": list(values.keys()), "share_pct": [v * 100.0 for v in values.values()]})


def _latent_components_table(row: pd.Series) -> pd.DataFrame:
    raw = _first(row, "latent_components_json", default="")
    if not raw:
        return pd.DataFrame()
    try:
        payload = json.loads(raw)
    except Exception:
        return pd.DataFrame()
    records: list[dict[str, Any]] = []
    for group in ("leverage_components", "trigger_components"):
        components = payload.get(group) or {}
        weights = (payload.get("weights") or {}).get("leverage" if group.startswith("leverage") else "trigger") or {}
        for name, value in components.items():
            records.append(
                {
                    "group": group.replace("_components", ""),
                    "component": name,
                    "value": value,
                    "weight": weights.get(name),
                }
            )
    return pd.DataFrame(records)


def _missing_required(frames: dict[str, pd.DataFrame]) -> list[str]:
    return [table for table in REQUIRED_TABLES if frames.get(table, pd.DataFrame()).empty]


def render() -> None:
    st.markdown("### ABM Market Simulation & Stress Monitor")
    st.caption(
        "Agent-based monitor for margin crowding, forced-selling amplification, "
        "panic ratio, and distance to cascade."
    )

    tables = {**REQUIRED_TABLES, **OPTIONAL_TABLES}
    frames = {table: _load_csv(table) for table in tables}
    scenario_frame = _load_csv(SCENARIO_TABLE)
    missing = _missing_required(frames)
    if missing:
        st.warning(
            "ABM data is incomplete. Missing required files: "
            + ", ".join(f"{table}.csv" for table in missing)
            + ". Run `python -m command.update_abm_data` after the LTMM ABM pipeline has produced gold CSVs."
        )
        with st.expander("Expected data files", expanded=False):
            st.write([f"{name}.csv" for name in tables])
        return

    merged = _merge_frames(frames)
    if merged.empty:
        st.error("ABM tables could not be aligned on `as_of_date`.")
        return

    latest = merged.iloc[-1]
    latest_date = _first(latest, "as_of_date")
    latest_date_label = latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else "N/A"
    regime = str(_first(latest, "regime_flag", default="N/A"))
    color = _regime_color(regime)
    distance = _float(latest, "distance_to_cascade")
    panic = _float(latest, "panic_ratio")
    leverage = _float(latest, "avg_leverage_ratio")
    confidence = _float(latest, "stress_confidence", "stress_confidence_stress_test", "stress_confidence_alert")
    quality = _float(latest, "input_quality_score", "input_quality_score_alert")
    early_warning = _float(latest, "early_warning_score")
    early_level = str(_first(latest, "early_warning_level", default="N/A"))
    warning_basis = str(_first(latest, "warning_basis", default="N/A"))
    warning_basis_label = _format_warning_basis(warning_basis)
    warning_color = _warning_level_color(early_level, early_warning)
    warning_score_label = _fmt_num(early_warning, 1, "/100") if early_warning is not None else "N/A"
    qp_panel_available = _boolish(_first(latest, "qp_panel_available", "alert_uses_quant_platform_panel", default=False))
    qp_panel_quality = _float(latest, "qp_panel_quality")

    top_col1, top_col2 = st.columns([1, 1.45])
    with top_col1:
        st.markdown(
            (
                "<div style='border:1px solid {color};border-radius:6px;padding:14px;text-align:center;height:100%;'>"
                "<div style='font-size:0.78rem;color:{color};font-weight:700;'>REGIME</div>"
                "<div style='font-size:1.22rem;color:{color};font-weight:700;margin-top:8px;'>{regime}</div>"
                "<div style='font-size:0.76rem;color:#6c757d;margin-top:8px;'>As of {date}</div>"
                "</div>"
            ).format(color=color, regime=regime, date=latest_date_label),
            unsafe_allow_html=True,
        )
    with top_col2:
        st.markdown(
            (
                "<div style='border:1px solid {warning_color};border-radius:6px;padding:14px;'>"
                "<div style='display:flex;justify-content:space-between;gap:12px;align-items:flex-start;'>"
                "<div>"
                "<div style='font-size:0.78rem;color:{warning_color};font-weight:700;'>EARLY-WARNING SCORE</div>"
                "<div style='font-size:1.85rem;color:{warning_color};font-weight:800;line-height:1.2;margin-top:4px;'>{score}</div>"
                "</div>"
                "<div style='font-size:0.95rem;color:{warning_color};font-weight:700;text-align:right;'>{level}</div>"
                "</div>"
                "<div style='font-size:0.78rem;color:#6c757d;margin-top:8px;'>Basis: {basis}</div>"
                "</div>"
            ).format(
                warning_color=warning_color,
                score=warning_score_label,
                level=early_level,
                basis=warning_basis_label,
            ),
            unsafe_allow_html=True,
        )
        if early_warning is not None:
            st.progress(max(0, min(100, int(round(early_warning)))))

    warning_message = f"Early-warning score: {warning_score_label} ({early_level}) | Drivers: {warning_basis_label}"
    if early_warning is None:
        st.info("Early-warning score is not available in the latest ABM alert file.")
    elif str(early_level).upper() in {"RED", "ORANGE", "YELLOW"}:
        st.warning(warning_message)
    else:
        st.success(warning_message)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Distance to Cascade", _fmt_pct(distance))
    with col2:
        st.metric("Panic Ratio", _fmt_pct(panic))
    with col3:
        st.metric("Avg Leverage", _fmt_num(leverage, suffix="x"))
    with col4:
        st.metric("Stress Confidence", _fmt_pct(confidence, 0))

    st.caption(
        f"As of {latest_date_label} | Input quality: {_fmt_pct(quality, 0)} | "
        f"Rows aligned: {len(merged)}"
    )
    if qp_panel_available:
        st.caption(
            "Data note: Early-warning score uses additional quant-platform stock price/volume panel "
            f"features when available. Latest panel quality: {_fmt_pct(qp_panel_quality, 0)}."
        )

    if regime in {"CASCADE_WARNING", "CASCADE_RISK"} or (distance is not None and distance <= 0.02):
        st.error("Cascade warning: margin-call distance is extremely narrow. Prioritize de-risking and liquidity.")
    elif regime in {"LEVERAGE_STRESS", "STRESS_RISING"} or (distance is not None and distance <= 0.05):
        st.warning("Leverage stress: avoid adding leverage and monitor weak-liquidity positions closely.")
    elif regime == "POST_SHOCK_STRESS":
        st.warning("Post-shock stress: market damage is already visible; treat signals as containment rather than early warning.")
    elif regime in {"FRAGILITY_BUILDUP", "MARGIN_BUILDUP", "BUBBLE_BUILDING"}:
        st.info("Margin buildup: leverage/crowding risk is accumulating, but cascade is not yet confirmed.")
    else:
        st.success("ABM state is not flagging immediate cascade stress.")

    tab_agents, tab_stress, tab_scenarios, tab_latent, tab_data = st.tabs(
        ["Agent Mix", "Stress Test", "Scenario Grid", "Cascade & Latent State", "Data"]
    )

    with tab_agents:
        mix_frame = _agent_mix_frame(latest)
        fig = px.pie(
            mix_frame,
            names="agent",
            values="share_pct",
            title="Current agent population share",
            color="agent",
            hole=0.36,
        )
        fig.update_traces(
            textposition="inside",
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="%{label}: %{value:.2f}%<extra></extra>",
        )
        fig.update_layout(
            legend=dict(orientation="h", y=1.08),
            margin=dict(l=10, r=10, t=56, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(mix_frame.sort_values("share_pct", ascending=False), use_container_width=True, hide_index=True)

        if len(merged) > 1:
            plot_df = merged[["as_of_date", "pct_fundamental", "pct_momentum", "pct_foreign", "pct_leveraged"]].copy()
            if "pct_noise" in merged.columns:
                plot_df["pct_noise"] = merged["pct_noise"]
            else:
                known = plot_df[["pct_fundamental", "pct_momentum", "pct_foreign", "pct_leveraged"]].sum(axis=1)
                plot_df["pct_noise"] = (1.0 - known).clip(lower=0.0)
            plot_df = plot_df.rename(
                columns={
                    "pct_fundamental": "Fundamental",
                    "pct_momentum": "Momentum",
                    "pct_foreign": "Foreign",
                    "pct_leveraged": "Leveraged",
                    "pct_noise": "Noise",
                }
            )
            for col in ["Fundamental", "Momentum", "Foreign", "Leveraged", "Noise"]:
                plot_df[col] = plot_df[col] * 100.0
            fig = px.bar(
                plot_df,
                x="as_of_date",
                y=["Fundamental", "Momentum", "Foreign", "Leveraged", "Noise"],
                title="Agent mix history",
                labels={"value": "Share (%)", "as_of_date": "Date", "variable": "Agent"},
            )
            fig.update_traces(hovertemplate="%{fullData.name}: %{y:.2f}%<extra></extra>")
            fig.update_layout(
                barmode="stack",
                bargap=0.18,
                hovermode="x unified",
                legend=dict(orientation="h", y=1.08),
                margin=dict(l=10, r=10, t=56, b=10),
            )
            fig.update_yaxes(range=[0, 100], ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)

    with tab_stress:
        if len(merged) == 1:
            stress_frame = pd.DataFrame(
                {
                    "component": ["Total drawdown", "Exogenous drawdown", "Endogenous drawdown"],
                    "value_pct": [
                        (_float(latest, "dd_total") or 0.0) * 100.0,
                        (_float(latest, "dd_exogenous") or 0.0) * 100.0,
                        (_float(latest, "dd_endogenous") or 0.0) * 100.0,
                    ],
                }
            )
            fig = px.bar(stress_frame, x="component", y="value_pct", title="Shock drawdown decomposition")
            st.plotly_chart(fig, use_container_width=True)
        else:
            fig = go.Figure()
            for col, label, color_line in [
                ("dd_total", "Total DD", "crimson"),
                ("dd_exogenous", "Exogenous DD", "seagreen"),
                ("dd_endogenous", "Endogenous DD", "orange"),
            ]:
                if col in merged.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=merged["as_of_date"],
                            y=merged[col] * 100.0,
                            mode="lines+markers",
                            name=label,
                            line=dict(color=color_line),
                        )
                    )
            if "panic_ratio" in merged.columns:
                fig.add_trace(
                    go.Scatter(
                        x=merged["as_of_date"],
                        y=merged["panic_ratio"] * 100.0,
                        mode="lines+markers",
                        name="Panic Ratio",
                        yaxis="y2",
                        line=dict(color="purple", dash="dash"),
                    )
                )
            fig.update_layout(
                yaxis=dict(title="Drawdown (%)"),
                yaxis2=dict(title="Panic Ratio (%)", overlaying="y", side="right", range=[0, 100]),
                legend=dict(orientation="h", y=1.08),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.write(
            {
                "dd_total": _fmt_pct(_float(latest, "dd_total")),
                "dd_exogenous": _fmt_pct(_float(latest, "dd_exogenous")),
                "dd_endogenous": _fmt_pct(_float(latest, "dd_endogenous")),
                "margin_call_events": _first(latest, "margin_call_events", "margin_calls", default="N/A"),
                "simulation_runs": _first(latest, "simulation_runs", default="N/A"),
            }
        )

    with tab_scenarios:
        if scenario_frame.empty:
            st.info("Scenario-grid output is not available yet.")
        else:
            latest_scenarios = scenario_frame[scenario_frame["as_of_date"].eq(scenario_frame["as_of_date"].max())].copy()
            latest_scenarios = latest_scenarios.sort_values(["scenario_rank", "scenario_name"])
            plot_cols = [col for col in ["scenario_name", "dd_total", "dd_endogenous", "panic_ratio"] if col in latest_scenarios.columns]
            if {"scenario_name", "dd_total"}.issubset(latest_scenarios.columns):
                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=latest_scenarios["scenario_name"],
                        y=latest_scenarios["dd_total"] * 100.0,
                        name="Total DD",
                        marker_color="#c1121f",
                    )
                )
                if "dd_endogenous" in latest_scenarios.columns:
                    fig.add_trace(
                        go.Bar(
                            x=latest_scenarios["scenario_name"],
                            y=latest_scenarios["dd_endogenous"] * 100.0,
                            name="Endogenous DD",
                            marker_color="#f77f00",
                        )
                    )
                fig.update_layout(
                    barmode="group",
                    yaxis_title="Drawdown (%)",
                    legend=dict(orientation="h", y=1.08),
                )
                st.plotly_chart(fig, use_container_width=True)
            if plot_cols:
                display = latest_scenarios.copy()
                for col in ["dd_total", "dd_exogenous", "dd_endogenous", "panic_ratio", "shock_magnitude"]:
                    if col in display.columns:
                        display[col] = display[col].astype(float)
                st.dataframe(display.tail(50), use_container_width=True)

    with tab_latent:
        st.markdown("#### Early-warning score")
        ew_col1, ew_col2, ew_col3 = st.columns([1, 1, 2])
        with ew_col1:
            st.metric("Score", warning_score_label)
        with ew_col2:
            st.metric("Level", early_level)
        with ew_col3:
            st.markdown("**Drivers**")
            st.caption(warning_basis_label)

        if early_warning is None:
            st.info("Early-warning score is not available in the latest ABM alert file.")
        elif str(early_level).upper() in {"RED", "ORANGE", "YELLOW"}:
            st.warning(warning_message)
        else:
            st.success(warning_message)

        if "distance_to_cascade" in merged.columns and len(merged) > 1:
            fig = px.line(
                merged,
                x="as_of_date",
                y=merged["distance_to_cascade"] * 100.0,
                labels={"y": "Distance (%)", "as_of_date": "Date"},
                title="Distance to cascade",
            )
            fig.add_hline(y=2.0, line_dash="dash", line_color="red", annotation_text="Critical 2%")
            fig.add_hline(y=5.0, line_dash="dash", line_color="orange", annotation_text="Warning 5%")
            st.plotly_chart(fig, use_container_width=True)

        if "early_warning_score" in merged.columns:
            ew_history_cols = ["as_of_date", "early_warning_score"]
            if "early_warning_level" in merged.columns:
                ew_history_cols.append("early_warning_level")
            if "warning_basis" in merged.columns:
                ew_history_cols.append("warning_basis")
            ew_history = merged[ew_history_cols].copy()
            ew_history["early_warning_score"] = pd.to_numeric(ew_history["early_warning_score"], errors="coerce")
            ew_history = ew_history.dropna(subset=["early_warning_score"])

            if ew_history.empty:
                st.info("No early-warning score history is available yet. Rerun the ABM v4 pipeline/backfill to populate it.")
            else:
                ew_history["date"] = pd.to_datetime(ew_history["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
                ew_history["date"] = ew_history["date"].fillna(ew_history["as_of_date"].astype(str))
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=ew_history["date"],
                        y=ew_history["early_warning_score"],
                        mode="lines+markers",
                        name="Early-warning score",
                        line=dict(color=warning_color, width=2),
                        marker=dict(size=9, color=warning_color),
                    )
                )
                fig.update_layout(
                    title="Early-warning score history",
                    xaxis_title="Date",
                    yaxis_title="Score",
                    xaxis=dict(type="category"),
                    yaxis=dict(range=[0, 100]),
                    margin=dict(l=10, r=10, t=56, b=10),
                )
                fig.add_hline(y=45.0, line_dash="dash", line_color="goldenrod", annotation_text="Yellow")
                fig.add_hline(y=60.0, line_dash="dash", line_color="orange", annotation_text="Orange")
                fig.add_hline(y=75.0, line_dash="dash", line_color="red", annotation_text="Red")
                st.plotly_chart(fig, use_container_width=True)
                ew_display = ew_history.sort_values("as_of_date", ascending=False)
                if "warning_basis" in ew_display.columns:
                    ew_display = ew_display.rename(columns={"warning_basis": "drivers"})
                    ew_display["drivers"] = ew_display["drivers"].map(_format_warning_basis)
                display_cols = [
                    col
                    for col in ["date", "early_warning_score", "early_warning_level", "drivers"]
                    if col in ew_display.columns
                ]
                st.dataframe(
                    ew_display[display_cols],
                    use_container_width=True,
                    hide_index=True,
                )
                if len(ew_history) < len(merged):
                    st.caption(
                        "Only ABM v4+ alert rows carry early-warning score; older rows remain blank until historical "
                        "backfill is rerun with the v4 methodology."
                    )
        else:
            st.info(
                "The current ABM alert file does not include `early_warning_score`. "
                "Rerun the upgraded ABM pipeline to create this column."
            )

        latent_cols = [
            "early_warning_score",
            "mli",
            "liquidity_stress",
            "margin_leverage_level",
            "margin_call_trigger_pressure",
            "cascade_vulnerability",
            "latent_confidence_score",
            "validation_quality",
        ]
        values = {
            col: _float(latest, col)
            for col in latent_cols
            if col in latest.index and _float(latest, col) is not None
        }
        if values:
            st.dataframe(pd.DataFrame([values]).T.rename(columns={0: "latest"}), use_container_width=True)

        components = _latent_components_table(latest)
        if not components.empty:
            st.markdown("#### Latent component contribution")
            st.dataframe(components, use_container_width=True)

    with tab_data:
        status_cols = [
            "as_of_date",
            "regime_flag",
            "early_warning_score",
            "early_warning_level",
            "warning_basis",
            "distance_to_cascade",
            "panic_ratio",
            "avg_leverage_ratio",
            "stress_confidence",
            "input_quality_score",
            "methodology_version",
            "validation_status",
        ]
        display_cols = [col for col in status_cols if col in merged.columns]
        st.dataframe(merged[display_cols].tail(50), use_container_width=True)
        with st.expander("Raw merged ABM data", expanded=False):
            st.dataframe(merged.tail(100), use_container_width=True)


show = render
