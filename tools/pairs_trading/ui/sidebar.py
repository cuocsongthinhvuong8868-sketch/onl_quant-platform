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

    st.sidebar.markdown("### DCC correlation filter")
    use_dcc_filter = st.sidebar.checkbox(
        "Enable DCC ρ filter",
        value=False,
        help=(
            "Lọc pair theo dynamic correlation tại last date. "
            "Pair với ρ < threshold = decoupling regime → skip entry. "
            "OFF mặc định vì compute thêm ~5-15s cho Aggregate/Live tab."
        ),
    )
    min_rho = st.sidebar.slider(
        "Min current ρ",
        min_value=-0.5, max_value=0.95, value=0.5, step=0.05,
        disabled=not use_dcc_filter,
        help=(
            "ρ_t < threshold → pair decoupling, skip. "
            "0.5 = moderately correlated. Mặc định 0.5 (literature)."
        ),
    )
    dcc_method = st.sidebar.selectbox(
        "ρ method",
        options=["ewma", "dcc"],
        index=0,
        disabled=not use_dcc_filter,
        help=(
            "ewma: RiskMetrics λ=0.94, O(T) per pair, recommended. "
            "dcc: bivariate DCC(1,1) MLE per pair, ~5-30s/pair, dùng cho audit."
        ),
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
        "use_dcc_filter": bool(use_dcc_filter),
        "min_rho": float(min_rho),
        "dcc_method": str(dcc_method),
    }
