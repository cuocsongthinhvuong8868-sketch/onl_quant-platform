"""
sidebar.py — Pairs Trading sidebar widgets.

Return dict params được tiêu thụ bởi page.py.
"""
from __future__ import annotations

import streamlit as st

from tools.pairs_trading.quant.clusters import PREDEFINED_CLUSTERS, CLUSTER_DESCRIPTIONS


def render_sidebar(available_tickers: list[str]) -> dict:
    """Render sidebar widgets → return params dict.

    available_tickers: từ load_close_prices().columns — dùng cho custom pair selectbox.
    """
    st.sidebar.markdown("### 📊 Pairs Trading Lab")

    cluster = st.sidebar.selectbox(
        "Cluster",
        options=list(PREDEFINED_CLUSTERS.keys()),
        index=0,
        help="Cụm cointegrated predefined. Ngữ cảnh kinh tế ở popup.",
    )
    with st.sidebar.expander("ℹ️ Cluster info"):
        st.markdown(f"**{cluster}**: {CLUSTER_DESCRIPTIONS.get(cluster, 'N/A')}")
        st.code(", ".join(PREDEFINED_CLUSTERS[cluster]))

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Entry/Exit thresholds")
    z_entry = st.sidebar.number_input(
        "Entry |z| threshold",
        min_value=1.0, max_value=4.0, value=2.0, step=0.1,
        help="Spec §13.3: |z|>2 mặc định",
    )
    z_stop = st.sidebar.number_input(
        "Stop-loss |z| threshold",
        min_value=2.0, max_value=5.0, value=3.0, step=0.1,
        help="Spec §13.3: |z|>3 → cointegration breakdown",
    )

    st.sidebar.markdown("### Half-life filter")
    hl_min, hl_max = st.sidebar.slider(
        "Half-life range (days)",
        min_value=1, max_value=60, value=(5, 30),
        help="Spec §13.3: chỉ trade pair half-life 5-30d",
    )

    st.sidebar.markdown("### Backtest window")
    lookback_years = st.sidebar.slider(
        "Lookback (years)",
        min_value=1, max_value=6, value=2,
        help="2 năm default cho backtest panel",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Custom pair")
    eligible_tickers = sorted(set(available_tickers))
    ct1 = st.sidebar.selectbox("Ticker 1 (Y / numerator)", options=eligible_tickers, index=0)
    ct2 = st.sidebar.selectbox(
        "Ticker 2 (X / hedge)",
        options=[t for t in eligible_tickers if t != ct1],
        index=0,
    )

    st.sidebar.markdown("---")
    tc_bps = st.sidebar.number_input(
        "Transaction cost (bps round-trip)",
        min_value=5.0, max_value=50.0, value=15.0, step=1.0,
        help="0.15% broker + 0% sell tax (BUY trade VN không tax)",
    )
    capital = st.sidebar.number_input(
        "Capital cho order ticket (nghìn VND)",
        min_value=10_000, max_value=10_000_000, value=200_000, step=10_000,
        help="200_000 = 200 triệu VND. Đơn vị nghìn VND khớp với price data.",
    )

    return {
        "cluster": cluster,
        "z_entry": float(z_entry),
        "z_stop": float(z_stop),
        "hl_min": int(hl_min),
        "hl_max": int(hl_max),
        "lookback_years": int(lookback_years),
        "custom_t1": ct1,
        "custom_t2": ct2,
        "tc_bps": float(tc_bps),
        "capital": int(capital),
    }
