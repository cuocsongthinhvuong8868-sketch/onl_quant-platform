"""
History Score & Regime — Hiển thị lịch sử điểm số và trạng thái thị trường
từ AI CIO Executive Summary (data_lake/Ai_cio_report.csv).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import DATA_LAKE
from shared.page_layout import render_signal_card

CSV_PATH = DATA_LAKE / "Ai_cio_report.csv"

# ── Regime → color mapping ──
REGIME_COLORS = {
    "capitulation": "#c0392b",
    "crisis":       "#e74c3c",
    "panic":        "#e67e22",
    "distribution": "#f1c40f",
    "fear":         "#f39c12",
    "neutral":      "#3498db",
    "picking":      "#34495e",
    "uptrend":      "#2ecc71",
    "expansion":    "#27ae60",
    "bull":         "#1abc9c",
    "greed":        "#16a085",
    "warning":      "#d35400",
}


def _regime_color(regime_str: str) -> str:
    """Trả về màu phù hợp nhất dựa trên keyword trong regime string."""
    regime_lower = str(regime_str).lower()
    for keyword, color in REGIME_COLORS.items():
        if keyword in regime_lower:
            return color
    return "#3498db"  # default blue


def _regime_tone(regime_str: str) -> str:
    regime_lower = str(regime_str).lower()
    if "capitulation" in regime_lower or "crisis" in regime_lower or "panic" in regime_lower:
        return "danger"
    if "fear" in regime_lower or "distribution" in regime_lower or "warning" in regime_lower:
        return "warning"
    if "uptrend" in regime_lower or "expansion" in regime_lower or "bull" in regime_lower:
        return "positive"
    return "neutral"


def render():
    st.markdown("## 📊 History Score & Regime")
    st.markdown(
        "Lịch sử điểm số **AI CIO Executive Summary** và trạng thái thị trường "
        "được ghi nhận hằng ngày từ workflow tự động."
    )
    st.markdown("---")

    # ── Load data ──
    if not CSV_PATH.exists():
        st.warning("⚠️ Chưa có dữ liệu. File `Ai_cio_report.csv` chưa tồn tại trong data_lake.")
        return

    try:
        df = pd.read_csv(CSV_PATH, dtype={"ddmmyyyy": str})
    except Exception as e:
        st.error(f"❌ Lỗi đọc file CSV: {e}")
        return

    if df.empty:
        st.info("ℹ️ File CSV rỗng — chưa có dữ liệu lịch sử.")
        return

    # ── Parse date ──
    df["date"] = pd.to_datetime(df["ddmmyyyy"], format="%d%m%Y", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["score"] = pd.to_numeric(df["score"], errors="coerce")

    # Backwards-compat: rows cũ thiếu cột source/provider → fill empty string
    for col in ("source", "provider"):
        if col not in df.columns:
            df[col] = ""
    df["source"] = df["source"].fillna("").astype(str)
    df["provider"] = df["provider"].fillna("").astype(str)

    # ── Summary metrics ──
    latest = df.iloc[-1]
    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
    with col1:
        st.metric("📅 Ngày gần nhất", latest["date"].strftime("%d/%m/%Y"))
    with col2:
        score_val = latest["score"]
        delta = None
        if len(df) >= 2:
            prev_score = df.iloc[-2]["score"]
            if pd.notna(prev_score) and pd.notna(score_val):
                delta = f"{score_val - prev_score:+.0f}"
        st.metric("📈 Score", f"{score_val:.0f}/100" if pd.notna(score_val) else "N/A", delta=delta)
    with col3:
        render_signal_card("🎯 Regime", latest["regime"], tone=_regime_tone(str(latest["regime"])))
    with col4:
        st.metric("📊 Số ngày", f"{len(df)}")

    st.markdown("---")

    # ── Chart ──
    st.subheader("📈 Biểu đồ Score & Regime theo thời gian")

    # Assign colors per point
    colors = [_regime_color(str(r)) for r in df["regime"]]

    fig = make_subplots(specs=[[{"secondary_y": False}]])

    # Line trace
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["score"],
            mode="lines+markers",
            name="Score & Regime",
            line=dict(color="#3498db", width=3),
            marker=dict(
                size=12,
                color=colors,
                line=dict(width=2, color="#ffffff"),
                symbol="circle",
            ),
            customdata=df["regime"],
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Score: <b>%{y}/100</b><br>"
                "Regime: <b>%{customdata}</b><br>"
                "<extra></extra>"
            ),
        )
    )

    # Regime zones background
    zone_bands = [
        (0, 7,    "rgba(192, 57, 43, 0.10)",   "Capitulation (0-7)"),
        (8, 14,   "rgba(231, 76, 60, 0.08)",   "Extreme Crisis (8-14)"),
        (15, 29,  "rgba(230, 126, 34, 0.08)",  "Pre-Crash / Panic (15-29)"),
        (30, 44,  "rgba(241, 196, 15, 0.08)",  "Fear / Distribution (30-44)"),
        (45, 59,  "rgba(52, 152, 219, 0.08)",  "Neutral / Stock-Picking (45-59)"),
        (60, 74,  "rgba(46, 204, 113, 0.08)",  "Uptrend / Expansion (60-74)"),
        (75, 89,  "rgba(39, 174, 96, 0.08)",   "Bull Confirmed (75-89)"),
        (90, 100, "rgba(26, 188, 156, 0.08)",  "Extreme Greed / Top Warning (90-100)"),
    ]
    for y0, y1, fill_color, label in zone_bands:
        fig.add_hrect(
            y0=y0, y1=y1,
            fillcolor=fill_color,
            line_width=0,
            annotation_text=label,
            annotation_position="right",
            annotation_font_size=10,
            annotation_font_color="rgba(100,100,100,0.6)",
        )

    # Threshold lines
    thresholds = [
        (7, "dot", "#c0392b"),
        (14, "dash", "#e74c3c"),
        (29, "dash", "#e67e22"),
        (44, "dash", "#f1c40f"),
        (59, "dash", "#3498db"),
        (74, "dash", "#2ecc71"),
        (89, "dot", "#27ae60"),
    ]
    for threshold, dash_style, color in thresholds:
        fig.add_hline(y=threshold, line_dash=dash_style, line_color=color,
                      line_width=1, opacity=0.4)

    fig.update_layout(
        height=500,
        margin=dict(l=50, r=150, t=30, b=50),
        yaxis=dict(
            title="Score (0–100)",
            range=[0, 105],
            gridcolor="rgba(128,128,128,0.15)",
        ),
        xaxis=dict(
            title="Ngày",
            gridcolor="rgba(128,128,128,0.15)",
            dtick="D1",
            tickformat="%d/%m",
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ── Table ──
    with st.expander("📋 Xem bảng dữ liệu chi tiết", expanded=False):
        # Render source thành emoji badge để dễ đọc
        def _source_badge(s: str) -> str:
            s = (s or "").lower()
            if s == "auto":
                return "🤖 Auto (cron)"
            if s == "manual":
                return "👤 Manual (user)"
            return "—"  # rows cũ trước upgrade

        display_df = df[["date", "score", "regime", "source", "provider"]].copy()
        display_df["date"] = display_df["date"].dt.strftime("%d/%m/%Y")
        display_df["source"] = display_df["source"].map(_source_badge)
        display_df["provider"] = display_df["provider"].replace("", "—")
        display_df.columns = ["Ngày", "Score", "Regime", "Nguồn", "Model"]
        # Reverse to show newest first
        display_df = display_df.iloc[::-1].reset_index(drop=True)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ngày": st.column_config.TextColumn("📅 Ngày", width="small"),
                "Score": st.column_config.NumberColumn("📈 Score", format="%d", width="small"),
                "Regime": st.column_config.TextColumn("🎯 Regime", width="large"),
                "Nguồn": st.column_config.TextColumn("🔧 Nguồn", width="small",
                                                      help="Auto = cron GitHub Actions; Manual = user chạy từ app"),
                "Model": st.column_config.TextColumn("🤖 Model", width="small"),
            },
        )

    # Stats về source distribution
    src_counts = df["source"].replace("", "legacy").value_counts().to_dict()
    src_summary = " • ".join(f"{k}: {v}" for k, v in src_counts.items())
    st.caption(f"Nguồn: `data_lake/Ai_cio_report.csv` • {len(df)} bản ghi  ({src_summary})")


if __name__ == "__main__":
    render()
