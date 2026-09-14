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
        min_value=float(z_entry + 0.1), max_value=6.0,
        value=float(max(3.0, z_entry + 0.5)), step=0.1,
        help="Spec §13.3: |z|>3 → cointegration breakdown",
    )
    z_method = st.sidebar.selectbox(
        "Z-score estimator",
        options=["standard", "robust", "ewma"],
        index=0,
        help="Tất cả estimator dùng location/scale đến t-1. Robust=MAD; EWMA thích nghi volatility.",
    )

    st.sidebar.markdown("### Half-life filter")
    hl_min, hl_max = st.sidebar.slider(
        "Half-life range (days)",
        min_value=1, max_value=60, value=(5, 30),
        help="Spec §13.3: chỉ trade pair half-life 5-30d",
    )

    st.sidebar.markdown("### DCC correlation filter")
    use_dcc_filter = st.sidebar.checkbox(
        "Enable dynamic-correlation gate",
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
    require_stability = st.sidebar.checkbox(
        "Require stable hedge ratio",
        value=True,
        help="Reject pair nếu rolling beta drift/CV vượt 25%.",
    )

    st.sidebar.markdown("### Universe Scanner")
    same_sector_only = st.sidebar.checkbox(
        "Chỉ pair cùng industry",
        value=True,
        help=(
            "Same `industry_code` từ ticker_metadata.csv. "
            "Tăng signal-to-noise — economic linkage thật, không spurious correlation."
        ),
    )
    cross_exchange = st.sidebar.checkbox(
        "Cho phép cross-exchange (HOSE × UPCOM)",
        value=False,
        help="UPCOM thanh khoản thấp — default OFF để tránh execution risk.",
    )
    min_rho_screen = st.sidebar.slider(
        "Scanner: min ρ_60d",
        min_value=0.5, max_value=0.95, value=0.75, step=0.05,
        help=(
            "Pearson correlation trên 60 phiên gần nhất. "
            "Lower = nhiều candidate hơn nhưng noise tăng. Default 0.75."
        ),
    )
    min_adv_bn = st.sidebar.number_input(
        "Min median ADV20 mỗi leg (tỷ VND)",
        min_value=0.1, max_value=1_000.0, value=1.0, step=0.5,
    )

    st.sidebar.markdown("### Backtest window")
    lookback_years = st.sidebar.slider(
        "Lookback (years)",
        min_value=2, max_value=8, value=3,
        help="2 năm default cho backtest panel",
    )
    formation_window = st.sidebar.select_slider(
        "Formation window (sessions)",
        options=[126, 252, 378, 504],
        value=252,
    )
    refit_every = st.sidebar.select_slider(
        "Refit cadence (sessions)",
        options=[5, 10, 20, 40, 60],
        value=20,
    )
    hedge_method = st.sidebar.selectbox(
        "Hedge sizing model",
        options=["ols", "rolling", "kalman"],
        index=0,
        help="Signal eligibility vẫn dùng EG OLS; rolling/Kalman là causal sizing challengers.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Custom pair")
    eligible_tickers = sorted(set(available_tickers))

    # Forward scanner-validated pair vào widget state TRƯỚC khi selectbox render.
    # Pattern: scanner tab set scanner_target_t1/t2 + st.rerun() → sidebar consume.
    if "scanner_target_t1" in st.session_state:
        target = st.session_state.pop("scanner_target_t1")
        if target in eligible_tickers:
            st.session_state["pairs_custom_t1"] = target
    if "scanner_target_t2" in st.session_state:
        target = st.session_state.pop("scanner_target_t2")
        if target in eligible_tickers:
            st.session_state["pairs_custom_t2"] = target

    ct1 = st.sidebar.selectbox(
        "Ticker 1 (Y / numerator)",
        options=eligible_tickers,
        key="pairs_custom_t1",
    )
    remaining = [t for t in eligible_tickers if t != ct1]
    # Clamp t2 nếu out-of-options (khi user đổi t1)
    if st.session_state.get("pairs_custom_t2") not in remaining and remaining:
        st.session_state["pairs_custom_t2"] = remaining[0]
    ct2 = st.sidebar.selectbox(
        "Ticker 2 (X / hedge)",
        options=remaining,
        key="pairs_custom_t2",
    )

    st.sidebar.markdown("---")
    tc_bps = st.sidebar.number_input(
        "Broker + slippage (bps one-way)",
        min_value=0.0, max_value=100.0, value=15.0, step=1.0,
        help="Áp trên traded notional ở cả entry/exit; không bao gồm thuế bán.",
    )
    sell_tax_bps = st.sidebar.number_input(
        "Sell tax (bps)",
        min_value=0.0, max_value=50.0, value=10.0, step=1.0,
    )
    borrow_bps_annual = st.sidebar.number_input(
        "Borrow cost (bps/year)",
        min_value=0.0, max_value=5_000.0, value=500.0, step=50.0,
    )
    capital = st.sidebar.number_input(
        "Capital cho order ticket (nghìn VND)",
        min_value=10_000, max_value=10_000_000, value=200_000, step=10_000,
        help="200_000 = 200 triệu VND. Đơn vị nghìn VND khớp với price data.",
    )
    max_pair_weight = st.sidebar.slider(
        "Portfolio max weight / pair",
        min_value=0.05, max_value=1.0, value=0.25, step=0.05,
    )

    st.sidebar.markdown("---")
    with st.sidebar.expander("Execution verification (required for ticket)"):
        adjusted_verified = st.checkbox(
            "Đã đối soát adjusted prices/corporate actions", value=False, key="pairs_adjusted_verified"
        )
        borrow_confirmed = st.checkbox(
            "Đã xác nhận borrow inventory và fee", value=False, key="pairs_borrow_confirmed"
        )
        shortable = st.checkbox(
            "Short leg thuộc danh sách được phép", value=False, key="pairs_shortable"
        )
        foreign_room_verified = st.checkbox(
            "Đã xác minh FOL/foreign room", value=False, key="pairs_fol_verified"
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
        "sell_tax_bps": float(sell_tax_bps),
        "borrow_bps_annual": float(borrow_bps_annual),
        "capital": int(capital),
        "use_dcc_filter": bool(use_dcc_filter),
        "min_rho": float(min_rho),
        "dcc_method": str(dcc_method if use_dcc_filter else "ewma"),
        "z_method": str(z_method),
        "require_stability": bool(require_stability),
        "formation_window": int(formation_window),
        "refit_every": int(refit_every),
        "hedge_method": str(hedge_method),
        "min_adv_vnd": float(min_adv_bn) * 1_000_000_000.0,
        "max_pair_weight": float(max_pair_weight),
        "adjusted_verified": bool(adjusted_verified),
        "borrow_confirmed": bool(borrow_confirmed),
        "shortable": bool(shortable),
        "foreign_room_verified": bool(foreign_room_verified),
        "same_sector_only": bool(same_sector_only),
        "cross_exchange": bool(cross_exchange),
        "min_rho_screen": float(min_rho_screen),
    }
