import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import DATA_LAKE
from tools.pvgo.freshness import DEFAULT_MARKET_DATA_PATH, evaluate_pvgo_freshness


DATA_PATH = DATA_LAKE / "pvgo" / "vnindex_valuation_history.csv"
MARKET_DATA_PATH = DEFAULT_MARKET_DATA_PATH


def calculate_pvgo(pe: float, coe_pct: float) -> float:
    coe_dec = coe_pct / 100.0
    if pd.isna(pe) or pe <= 0 or coe_dec <= 0:
        return float("nan")
    return (1.0 - 1.0 / (coe_dec * pe)) * 100.0


def get_pvgo_status(pvgo: float) -> dict[str, str]:
    if pd.isna(pvgo):
        return {
            "label": "N/A",
            "guidance": "No valuation signal.",
            "color": "#71717a",
            "bg": "rgba(113, 113, 122, 0.10)",
        }
    if pvgo < 0:
        return {
            "label": "Below steady-state value",
            "guidance": "Potentially cheap, but check earnings sustainability.",
            "color": "#16a34a",
            "bg": "rgba(22, 163, 74, 0.10)",
        }
    if pvgo < 20:
        return {
            "label": "Low expectations",
            "guidance": "Usually attractive if earnings quality is decent.",
            "color": "#22c55e",
            "bg": "rgba(34, 197, 94, 0.10)",
        }
    if pvgo < 35:
        return {
            "label": "Normal / fair",
            "guidance": "Neutral zone; rely on quality and cycle signals.",
            "color": "#ca8a04",
            "bg": "rgba(202, 138, 4, 0.12)",
        }
    if pvgo < 50:
        return {
            "label": "Elevated",
            "guidance": "Requires growth quality confirmation.",
            "color": "#f97316",
            "bg": "rgba(249, 115, 22, 0.12)",
        }
    if pvgo < 65:
        return {
            "label": "Very high",
            "guidance": "High expectation risk; stress test assumptions.",
            "color": "#ea580c",
            "bg": "rgba(234, 88, 12, 0.14)",
        }
    return {
        "label": "Extreme",
        "guidance": "Priced for perfection; avoid unless exceptional quality.",
        "color": "#dc2626",
        "bg": "rgba(220, 38, 38, 0.12)",
    }


@st.cache_data(show_spinner=False)
def load_pvgo_history(path: str | Path = DATA_PATH, file_mtime: float | None = None) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("close", "pe", "pb"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df.loc[df["pe"] <= 0, "pe"] = np.nan
    df.loc[df["pb"] <= 0, "pb"] = np.nan
    df["pe"] = df["pe"].interpolate(method="linear").ffill().bfill()
    df["pb"] = df["pb"].interpolate(method="linear").ffill().bfill()
    return df


@st.cache_data(show_spinner=False)
def load_vnindex_history(
    path: str | Path = MARKET_DATA_PATH,
    file_mtime: float | None = None,
) -> pd.DataFrame:
    """Load the canonical VN-Index market feed independently of valuation data."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["date", "close", "volume"])

    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["date", "close", "volume"])

    columns = {str(column).strip().lower(): column for column in df.columns}
    date_column = next(
        (columns[name] for name in ("time", "date", "trading_date") if name in columns),
        None,
    )
    close_column = next(
        (columns[name] for name in ("vnindex", "close") if name in columns),
        None,
    )
    if date_column is None or close_column is None:
        return pd.DataFrame(columns=["date", "close", "volume"])

    market = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_column], errors="coerce"),
            "close": pd.to_numeric(df[close_column], errors="coerce"),
        }
    )
    volume_column = next(
        (columns[name] for name in ("vnindex_volume", "volume") if name in columns),
        None,
    )
    market["volume"] = (
        pd.to_numeric(df[volume_column], errors="coerce") if volume_column is not None else np.nan
    )
    return (
        market.dropna(subset=["date", "close"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _metric_card(label: str, value: str, caption: str | None = None) -> None:
    st.markdown(
        f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;background:#ffffff;">
          <div style="font-size:12px;color:#71717a;font-weight:600;text-transform:uppercase;">{label}</div>
          <div style="font-size:24px;font-weight:700;color:#111827;margin-top:4px;">{value}</div>
          <div style="font-size:12px;color:#71717a;margin-top:4px;">{caption or ""}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_freshness_status(freshness: dict[str, str | int | None]) -> None:
    status = freshness["status"]
    source_date = freshness["source_date"] or "unknown"
    market_date = freshness["market_date"] or "unknown"
    session_lag = freshness["session_lag"]
    max_lag = freshness["max_session_lag"]

    if status == "STALE":
        st.warning(
            "P/E and P/B valuation freshness: STALE. "
            f"Valuation source {source_date} is {session_lag} market sessions behind the latest "
            f"VN-Index market session {market_date}; the valuation limit is {max_lag}. "
            "This warning does not mean that the separate VN-Index price feed is stale."
        )
    elif status == "CURRENT":
        message = (
            f"P/E and P/B valuation freshness: CURRENT. Valuation source {source_date}; latest "
            f"VN-Index market session {market_date}; valuation lag {session_lag}/{max_lag}."
        )
        if session_lag:
            st.info(message)
        else:
            st.success(message)
    else:
        st.warning(
            "P/E and P/B valuation freshness: UNKNOWN. "
            f"Valuation source date {source_date}; latest VN-Index market session {market_date}."
        )


def _matrix_html(selected_pe: float, selected_coe: float) -> str:
    coes = np.arange(9.0, 17.5, 0.5)
    pes = np.arange(9.0, 17.5, 0.5)
    html = """
    <div style="overflow-x:auto;max-height:480px;">
    <table style="width:100%;border-collapse:separate;border-spacing:2px;font-size:12px;">
    <thead><tr><th style="padding:6px;border:1px solid #e5e7eb;background:#f9fafb;">P/E \\ COE</th>
    """
    for coe in coes:
        html += f'<th style="padding:6px;border:1px solid #e5e7eb;background:#f9fafb;">{coe:.1f}%</th>'
    html += "</tr></thead><tbody>"

    for pe in pes[::-1]:
        html += f'<tr><td style="padding:6px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:700;text-align:center;">{pe:.1f}x</td>'
        for coe in coes:
            pvgo = calculate_pvgo(pe, coe)
            status = get_pvgo_status(pvgo)
            highlight = abs(pe - selected_pe) < 0.24 and abs(coe - selected_coe) < 0.24
            border = "2px solid #111827" if highlight else "1px solid transparent"
            html += (
                f'<td title="COE: {coe:.1f}%, P/E: {pe:.1f}x, PVGO: {pvgo:.1f}%" '
                f'style="padding:6px;text-align:center;border:{border};border-radius:4px;'
                f'background:{status["bg"]};color:{status["color"]};font-weight:{"700" if highlight else "500"};">'
                f"{pvgo:.1f}%</td>"
            )
        html += "</tr>"
    html += "</tbody></table></div>"
    return html


def _plot_vnindex(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["close"],
            name="VN-Index",
            mode="lines",
            line=dict(color="#2563eb", width=2),
        )
    )
    fig.update_layout(
        height=380,
        margin=dict(l=35, r=25, t=25, b=35),
        yaxis=dict(title="VN-Index points", gridcolor="rgba(0,0,0,0.06)"),
        showlegend=False,
    )
    return fig


def _plot_pe(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["pe"],
            name="P/E",
            mode="lines",
            line=dict(color="#f59e0b", width=1.6, dash="dash"),
        )
    )
    fig.update_layout(
        height=380,
        margin=dict(l=35, r=25, t=25, b=35),
        yaxis=dict(title="P/E (x)", ticksuffix="x", gridcolor="rgba(0,0,0,0.06)"),
        showlegend=False,
    )
    return fig


def _plot_pvgo(df: pd.DataFrame, coe: float) -> go.Figure:
    plot_df = df.copy()
    plot_df["pvgo"] = plot_df["pe"].apply(lambda pe: calculate_pvgo(pe, coe))
    avg = plot_df["pvgo"].mean()
    std = plot_df["pvgo"].std()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["pvgo"],
            name="PVGO",
            mode="lines",
            line=dict(color="#10b981", width=2.5),
        )
    )
    if not math.isnan(avg):
        fig.add_hline(y=avg, line_dash="dash", line_color="#71717a", annotation_text=f"Avg {avg:.1f}%")
        fig.add_hline(y=avg + std, line_dash="dot", line_color="#dc2626", annotation_text="+1 SD")
        fig.add_hline(y=avg - std, line_dash="dot", line_color="#dc2626", annotation_text="-1 SD")
    fig.update_layout(
        height=380,
        margin=dict(l=35, r=25, t=25, b=35),
        yaxis=dict(title="PVGO %", ticksuffix="%", gridcolor="rgba(0,0,0,0.06)"),
        showlegend=False,
    )
    return fig


def render() -> None:
    st.title("PVGO Valuation Model")
    st.caption("Present Value of Growth Opportunities for VN-Index. Data-only tool, no AI analysis.")

    market_data_mtime = MARKET_DATA_PATH.stat().st_mtime if MARKET_DATA_PATH.exists() else None
    market_df = load_vnindex_history(MARKET_DATA_PATH, market_data_mtime)
    st.markdown("### VN-Index Market Data")
    if market_df.empty:
        st.warning("VN-Index market data is unavailable. This is independent of the valuation feed.")
    else:
        latest_market = market_df.iloc[-1]
        latest_market_date = latest_market["date"].strftime("%d/%m/%Y")
        market_left, market_right = st.columns(2)
        with market_left:
            _metric_card("Latest VN-Index", f"{float(latest_market['close']):,.2f}", latest_market_date)
        with market_right:
            _metric_card("Latest market session", latest_market_date, "Canonical VN-Index price feed")
        st.caption("VN-Index prices are loaded from the canonical market feed, separately from P/E and P/B.")

    st.markdown("### P/E and P/B Valuation Data")
    data_mtime = DATA_PATH.stat().st_mtime if DATA_PATH.exists() else None
    df = load_pvgo_history(DATA_PATH, data_mtime)
    if df.empty:
        st.warning(
            "No P/E/P/B valuation data is available. Run `python command/update_pvgo_valuation.py` "
            "or wait for the scheduled refresh."
        )
        return

    latest = df.iloc[-1]
    latest_date = latest["date"].strftime("%d/%m/%Y")
    data_updated_at = latest.get("scraped_at", "")
    freshness = evaluate_pvgo_freshness(latest["date"])
    _render_freshness_status(freshness)

    coe = st.sidebar.slider(
        "Cost of Equity (COE %)",
        min_value=5.0,
        max_value=25.0,
        value=14.0,
        step=0.1,
        key="pvgo_coe",
    )

    date_labels = df["date"].dt.strftime("%d/%m/%Y").tolist()[::-1]
    selected_label = st.sidebar.selectbox(
        "Valuation analysis date (P/E and P/B)",
        date_labels,
        index=0,
        key="pvgo_date",
    )
    selected_date = pd.to_datetime(selected_label, format="%d/%m/%Y")
    row = df.loc[df["date"] == selected_date].iloc[0]

    pe = float(row["pe"])
    pb = float(row["pb"])
    pvgo = calculate_pvgo(pe, coe)
    steady_state_pe = 1.0 / (coe / 100.0)
    status = get_pvgo_status(pvgo)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("P/E", f"{pe:.2f}x", f"Valuation date {selected_label}")
    with c2:
        _metric_card("P/B", f"{pb:.2f}x", f"Valuation date {selected_label}")
    with c3:
        _metric_card("Steady-State P/E", f"{steady_state_pe:.2f}x", f"COE {coe:.1f}%")
    with c4:
        _metric_card("Implied PVGO", f"{pvgo:.1f}%", status["label"])

    st.markdown(
        f"""
        <div style="border:1px solid {status['color']};border-radius:8px;padding:14px 16px;
                    background:{status['bg']};margin:16px 0;">
          <div style="font-weight:700;color:{status['color']};">Expectation Level: {status['label']}</div>
          <div style="margin-top:6px;color:#111827;">
            Observed P/E is <b>{pe:.2f}x</b> versus steady-state P/E <b>{steady_state_pe:.2f}x</b>.
            The market is pricing <b>{pvgo:.1f}%</b> of value into growth opportunities.
          </div>
          <div style="margin-top:6px;color:#111827;"><b>Guidance:</b> {status['guidance']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_matrix, tab_history = st.tabs(["PVGO Matrix", "Historical Trend"])
    with tab_matrix:
        st.markdown("#### Valuation Expectations Matrix")
        st.markdown(_matrix_html(pe, coe), unsafe_allow_html=True)

    with tab_history:
        left, right = st.columns(2)
        with left:
            st.markdown("#### VN-Index Price History")
            if market_df.empty:
                st.info("VN-Index market history is unavailable.")
            else:
                st.caption(
                    f"Canonical market feed through {latest_market_date}; independent of the valuation feed."
                )
                st.plotly_chart(_plot_vnindex(market_df), use_container_width=True)
        with right:
            st.markdown("#### P/E Valuation History")
            st.caption(
                f"24hmoney valuation feed through {latest_date}. Last scraper timestamp: {data_updated_at}"
            )
            st.plotly_chart(_plot_pe(df), use_container_width=True)

        st.markdown("#### PVGO History Derived from P/E")
        st.caption(f"Calculated from the P/E valuation feed through {latest_date} using COE {coe:.1f}%.")
        st.plotly_chart(_plot_pvgo(df, coe), use_container_width=True)
