"""
page.py — Pairs Trading Streamlit page.

5 tabs:
  1. Cluster Scan         — Johansen + half-life + dominant spread
  2. Pairwise Heatmap     — NxN EG p-value matrix
  3. Custom Pair          — Full EG + OU + Hurst + z-score + 2yr backtest
  4. Backtest aggregate   — All cointegrated pair trong cluster
  5. Live Signals (P2)    — Current cointegrated pair với |z|, order ticket gen

KHÔNG plug AI CIO (spec §13.5).
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd
import streamlit as st

from shared.data_loader import load_close_prices
from tools.pairs_trading.quant.clusters import (
    PREDEFINED_CLUSTERS,
    CLUSTER_DESCRIPTIONS,
    validate_clusters_against_universe,
)
from tools.pairs_trading.quant.cointegration import (
    engle_granger,
    johansen_test,
    ou_half_life_raw,
    hurst,
    pairwise_eg_matrix,
    HALF_LIFE_MIN,
    HALF_LIFE_MAX,
)
from tools.pairs_trading.quant.signal import (
    z_score_60d,
    entry_exit_rules,
    quarantine_flag,
)
from tools.pairs_trading.quant.backtest import (
    basket_pnl,
    summary_stats,
    generate_order_ticket,
    order_ticket_to_json,
)
from tools.pairs_trading.ui.sidebar import render_sidebar
from tools.pairs_trading.ui.charts import (
    render_spread_chart,
    render_cluster_heatmap,
    render_backtest_equity,
    render_residual_diagnostics,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────
# Cached compute (Streamlit-side)
# ─────────────────────────────────────────────────


@st.cache_data(ttl=86400, show_spinner=False)
def _load_prices_for_pairs(lookback_years: int) -> pd.DataFrame:
    """Load close prices restricted to lookback window."""
    prices = load_close_prices()
    end = prices.index[-1]
    start = end - pd.Timedelta(days=int(lookback_years * 365))
    return prices.loc[start:]


# ─────────────────────────────────────────────────
# Helper: warnings (FOL, lunch break, refit stale)
# ─────────────────────────────────────────────────


def _show_global_warnings() -> None:
    """Top-of-page banners — appear ở tất cả tab."""
    st.info(
        "⚠️ **Foreign Ownership Limit (FOL) check**: tool ASSUMES `foreign_room > 5%` cho tất cả ticker. "
        "Free-tier vnstock không cung cấp daily FOL data — manual verify trước khi submit order thực.",
        icon="ℹ️",
    )
    st.warning(
        "⚠️ **Corp-action**: prices KHÔNG explicit-adjusted cho split/dividend. vnstock KBS source "
        "thường default đã adjusted, nhưng edge case có thể fake-break cointegration tại corp-action date.",
        icon="📋",
    )

    # Lunch break ICT warning
    now = datetime.now()
    lunch_start = dtime(11, 30)
    lunch_end = dtime(13, 0)
    if lunch_start <= now.time() <= lunch_end:
        st.warning(
            f"🍱 **VN lunch break** ({now.strftime('%H:%M')}) — sàn nghỉ 11:30-13:00 ICT. "
            "Orders sẽ queue tới 13:00. Không auto-execute.",
            icon="⏰",
        )


# ─────────────────────────────────────────────────
# Tab 1: Cluster Scan (Johansen)
# ─────────────────────────────────────────────────


def _tab_cluster_scan(prices: pd.DataFrame, params: dict) -> None:
    cluster_name = params["cluster"]
    tickers_all = PREDEFINED_CLUSTERS[cluster_name]
    available = [t for t in tickers_all if t in prices.columns]
    missing = [t for t in tickers_all if t not in prices.columns]

    st.markdown(f"### Cluster: **{cluster_name}**")
    st.caption(CLUSTER_DESCRIPTIONS.get(cluster_name, ""))
    col1, col2 = st.columns([2, 1])
    with col1:
        st.write(f"Tickers: `{', '.join(available)}`" + (f" (missing: {missing})" if missing else ""))
    with col2:
        if len(available) < 2:
            st.error("Cần ≥2 ticker available")
            return

    if len(available) < 2:
        return

    # Johansen test
    sub = prices[available].dropna(how="any").loc["2018-01-01":]
    if len(sub) < 100:
        st.error(f"Chỉ {len(sub)} obs sau dropna+2018-filter — không đủ cho Johansen")
        return

    try:
        joh = johansen_test(sub)
    except Exception as exc:
        st.error(f"Johansen fit fail: {exc}")
        return

    # Display trace stat
    n = len(available)
    df_trace = pd.DataFrame(
        {
            "H0: r ≤": list(range(n)),
            "Trace stat": joh["trace_stat"].round(3),
            "Crit 95%": joh["trace_crit_95"].round(3),
            "Reject H0?": joh["trace_stat"] > joh["trace_crit_95"],
        }
    )
    st.markdown("#### Johansen trace statistics")
    st.dataframe(df_trace, use_container_width=True, hide_index=True)
    st.metric("n_coint_vectors (95% CI)", joh["n_coint_vectors"])

    if joh["n_coint_vectors"] == 0:
        st.warning(f"Cluster **{cluster_name}** không có cointegration vector ở 95% CI — pairs trade dùng cluster này có RISK.")

    # Dominant eigenvector → spread series
    if joh["n_coint_vectors"] >= 1:
        beta_vec = joh["eig_vectors"][:, 0]
        beta_norm = beta_vec / beta_vec[0]
        st.markdown("#### Dominant cointegrating vector (normalized to β₁=1)")
        df_beta = pd.DataFrame({"Ticker": available, "β": beta_norm.round(4)})
        st.dataframe(df_beta, use_container_width=True, hide_index=True)

        log_p = np.log(sub.values)
        spread_arr = log_p @ beta_vec
        spread = pd.Series(spread_arr, index=sub.index, name="spread")
        hl_raw = ou_half_life_raw(spread)
        z_series = z_score_60d(spread)
        sig = entry_exit_rules(
            z_series.dropna(),
            entry=params["z_entry"], stop=params["z_stop"],
            half_life=hl_raw,
        )
        col_hl, col_h = st.columns(2)
        col_hl.metric("OU half-life (days)", f"{hl_raw:.1f}" if np.isfinite(hl_raw) else "NaN")
        col_h.metric("Hurst H", f"{hurst(spread):.3f}")
        if np.isfinite(hl_raw) and not (HALF_LIFE_MIN <= hl_raw <= HALF_LIFE_MAX):
            st.warning(
                f"Half-life {hl_raw:.1f}d ngoài band [{HALF_LIFE_MIN}, {HALF_LIFE_MAX}] — "
                "<5d: noise (phí ăn hết); >30d: drift/regime change. Spec §13.3 → SKIP trade.",
                icon="⚠️",
            )

        st.plotly_chart(
            render_spread_chart(
                spread, z_series, sig,
                z_entry=params["z_entry"], z_stop=params["z_stop"],
                title=f"{cluster_name} Johansen spread",
            ),
            use_container_width=True,
        )


# ─────────────────────────────────────────────────
# Tab 2: Pairwise Heatmap
# ─────────────────────────────────────────────────


def _tab_pairwise(prices: pd.DataFrame, params: dict) -> None:
    cluster_name = params["cluster"]
    tickers = [t for t in PREDEFINED_CLUSTERS[cluster_name] if t in prices.columns]
    if len(tickers) < 2:
        st.error("Cần ≥2 ticker available trong cluster")
        return

    st.markdown(f"### Pairwise EG p-value — {cluster_name}")
    sub = prices[tickers].dropna(how="any").loc["2018-01-01":]
    with st.spinner("Computing EG matrix..."):
        M = pairwise_eg_matrix(sub, tickers)
    st.plotly_chart(render_cluster_heatmap(M, threshold=0.05), use_container_width=True)

    # Sort cointegrated pairs by p-value
    rows = []
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            if i < j:
                p = M.iloc[i, j]
                if pd.notna(p):
                    rows.append({"Pair": f"{t1}/{t2}", "p_value": p, "Cointegrated": p < 0.05})
    if rows:
        df = pd.DataFrame(rows).sort_values("p_value")
        st.markdown("#### Ranked pairs (low p = strong cointegration)")
        st.dataframe(df, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────
# Tab 3: Custom Pair (full pipeline)
# ─────────────────────────────────────────────────


def _tab_custom_pair(prices: pd.DataFrame, params: dict) -> None:
    t1, t2 = params["custom_t1"], params["custom_t2"]
    if t1 == t2:
        st.error("Chọn 2 ticker khác nhau")
        return
    if t1 not in prices.columns or t2 not in prices.columns:
        st.error(f"{t1} hoặc {t2} không có trong market_data")
        return

    st.markdown(f"### Custom pair: **{t1}** vs **{t2}**")
    sub = prices[[t1, t2]].dropna(how="any").loc["2018-01-01":]
    if len(sub) < 100:
        st.error(f"Chỉ {len(sub)} obs sau align — cần ≥100")
        return

    try:
        eg = engle_granger(sub[t1], sub[t2])
    except Exception as exc:
        st.error(f"EG fail: {exc}")
        return

    spread = eg["resid"]
    hl_raw = ou_half_life_raw(spread)
    h = hurst(spread)
    z_series = z_score_60d(spread)
    sig = entry_exit_rules(
        z_series.dropna(),
        entry=params["z_entry"], stop=params["z_stop"],
        half_life=hl_raw,
    )

    # Metrics row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("β (hedge ratio)", f"{eg['beta']:.4f}")
    c2.metric("ADF p-value", f"{eg['p_value']:.4f}",
              delta="cointegrated" if eg["is_cointegrated"] else "NOT cointegrated",
              delta_color="normal" if eg["is_cointegrated"] else "inverse")
    c3.metric("Half-life (d)", f"{hl_raw:.1f}" if np.isfinite(hl_raw) else "NaN")
    c4.metric("Hurst", f"{h:.3f}", delta="mean-revert" if h < 0.5 else "drift",
              delta_color="normal" if h < 0.5 else "inverse")
    c5.metric("Z latest", f"{z_series.dropna().iloc[-1]:.2f}" if z_series.notna().any() else "—")

    # Spread chart
    st.plotly_chart(
        render_spread_chart(
            spread, z_series, sig,
            z_entry=params["z_entry"], z_stop=params["z_stop"],
            title=f"{t1}/{t2} spread & z-score",
        ),
        use_container_width=True,
    )

    # Diagnostic chart
    with st.expander("📊 Residual diagnostics (ADF + ACF)"):
        st.plotly_chart(
            render_residual_diagnostics(spread, eg["adf_stat"], eg["p_value"]),
            use_container_width=True,
        )

    # Mini-backtest 2yr
    st.markdown("---")
    st.markdown(f"#### Mini-backtest {params['lookback_years']}yr")
    backtest_start = sub.index[-1] - pd.Timedelta(days=int(params["lookback_years"] * 365))
    bt_window = sub.loc[backtest_start:]
    if len(bt_window) < 120:
        st.warning("Backtest window <120 obs, skip")
        return
    try:
        bt_eg = engle_granger(bt_window[t1], bt_window[t2])
        bt_hl = ou_half_life_raw(bt_eg["resid"])
        bt_z = z_score_60d(bt_eg["resid"])
        bt_sig = entry_exit_rules(
            bt_z.dropna(), entry=params["z_entry"],
            stop=params["z_stop"], half_life=bt_hl,
        )
        eq = basket_pnl(bt_window, bt_eg["beta"], bt_sig, t1, t2, tc_bps=params["tc_bps"])
        if eq.empty:
            st.warning("Backtest empty — no overlap between signals and prices")
            return
        stats = summary_stats(eq)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total return", f"{stats['total_return']:.1%}")
        m2.metric("Sharpe", f"{stats['sharpe']:.2f}")
        m3.metric("Max DD", f"{stats['max_dd']:.1%}")
        m4.metric("Hit rate", f"{stats['hit_rate']:.1%}" if np.isfinite(stats["hit_rate"]) else "—")
        m5.metric("# Trades", stats["n_trades"])
        st.plotly_chart(render_backtest_equity(eq), use_container_width=True)
    except Exception as exc:
        st.error(f"Backtest fail: {exc}")


# ─────────────────────────────────────────────────
# Tab 4: Aggregate Backtest (all cointegrated pair trong cluster)
# ─────────────────────────────────────────────────


def _tab_aggregate_backtest(prices: pd.DataFrame, params: dict) -> None:
    cluster_name = params["cluster"]
    tickers = [t for t in PREDEFINED_CLUSTERS[cluster_name] if t in prices.columns]
    if len(tickers) < 2:
        st.error("Cần ≥2 ticker available")
        return

    st.markdown(f"### Aggregate backtest — {cluster_name}")
    backtest_start = prices.index[-1] - pd.Timedelta(days=int(params["lookback_years"] * 365))
    sub = prices.loc[backtest_start:, tickers].dropna(how="any")
    if len(sub) < 120:
        st.warning("Backtest window <120 obs, skip")
        return

    rows = []
    equity_curves = {}
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            if i >= j:
                continue
            try:
                eg = engle_granger(sub[t1], sub[t2])
                if not eg["is_cointegrated"]:
                    continue
                hl = ou_half_life_raw(eg["resid"])
                if not np.isfinite(hl) or not (params["hl_min"] <= hl <= params["hl_max"]):
                    continue
                z = z_score_60d(eg["resid"])
                sig = entry_exit_rules(
                    z.dropna(), entry=params["z_entry"],
                    stop=params["z_stop"], half_life=hl,
                )
                eq = basket_pnl(sub, eg["beta"], sig, t1, t2, tc_bps=params["tc_bps"])
                stats = summary_stats(eq)
                rows.append({
                    "Pair": f"{t1}/{t2}",
                    "β": round(eg["beta"], 4),
                    "p_value": round(eg["p_value"], 4),
                    "half_life": round(hl, 1),
                    "total_ret": stats["total_return"],
                    "sharpe": round(stats["sharpe"], 2),
                    "max_dd": round(stats["max_dd"], 4),
                    "n_trades": stats["n_trades"],
                })
                equity_curves[f"{t1}/{t2}"] = eq["equity"]
            except Exception as exc:
                logger.warning("Aggregate backtest fail %s/%s: %s", t1, t2, exc)

    if not rows:
        st.info(
            f"Không có pair nào pass filter (cointegrated + half-life ∈ [{params['hl_min']}, {params['hl_max']}]). "
            "Thử relax half-life range trong sidebar."
        )
        return

    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    df["total_ret"] = df["total_ret"].apply(lambda x: f"{x:.1%}")
    df["max_dd"] = df["max_dd"].apply(lambda x: f"{x:.1%}")
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Overlay equity curves
    if equity_curves:
        import plotly.graph_objects as go
        fig = go.Figure()
        for name, eq_series in equity_curves.items():
            fig.add_trace(go.Scatter(x=eq_series.index, y=eq_series.values, mode="lines", name=name))
        fig.update_layout(
            title=f"{cluster_name} — all qualifying pair equity",
            yaxis_title="Equity (1 = initial)",
            height=450, margin=dict(l=10, r=10, t=70, b=10),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────
# Tab 5: Live Signals (P2)
# ─────────────────────────────────────────────────


def _tab_live_signals(prices: pd.DataFrame, params: dict) -> None:
    cluster_name = params["cluster"]
    tickers = [t for t in PREDEFINED_CLUSTERS[cluster_name] if t in prices.columns]
    st.markdown(f"### Live signals — {cluster_name}")

    # Refit info banner
    last_refit_date = prices.index[-1]
    days_since = (datetime.now().date() - last_refit_date.date()).days
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(f"Last data date: **{last_refit_date.strftime('%Y-%m-%d')}** "
                   f"({days_since}d ago) — cointegration nên re-test mỗi 60 phiên")
    with col_b:
        if days_since > 60:
            st.error("🔴 STALE — refit needed")
        else:
            st.success("🟢 Fresh")

    # Compute live signal cho từng pair
    sub = prices.loc["2018-01-01":, tickers].dropna(how="any")
    if len(sub) < 120:
        st.error("Insufficient data")
        return

    rows = []
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            if i >= j:
                continue
            try:
                eg = engle_granger(sub[t1], sub[t2])
                if not eg["is_cointegrated"]:
                    continue
                hl = ou_half_life_raw(eg["resid"])
                if not (params["hl_min"] <= hl <= params["hl_max"]):
                    continue
                z = z_score_60d(eg["resid"]).dropna()
                if z.empty:
                    continue
                z_last = float(z.iloc[-1])
                quarantine = quarantine_flag(z, stop=params["z_stop"], days=60)
                in_quarantine = quarantine is not None and quarantine > pd.Timestamp(datetime.now())
                action = "FLAT"
                if not in_quarantine:
                    if z_last < -params["z_entry"]:
                        action = f"LONG SPREAD (long {t1}, short {t2})"
                    elif z_last > params["z_entry"]:
                        action = f"SHORT SPREAD (short {t1}, long {t2})"
                rows.append({
                    "Pair": f"{t1}/{t2}",
                    "β": round(eg["beta"], 4),
                    "z_now": round(z_last, 2),
                    "half_life": round(hl, 1),
                    "action": action,
                    "quarantine_until": quarantine.strftime("%Y-%m-%d") if in_quarantine else "—",
                })
            except Exception as exc:
                logger.warning("Live signal fail %s/%s: %s", t1, t2, exc)

    if not rows:
        st.info(f"Không có pair nào qualify trong cluster {cluster_name}.")
        return

    df = pd.DataFrame(rows).sort_values("z_now", key=lambda s: s.abs(), ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Order ticket generator
    st.markdown("---")
    st.markdown("#### Generate Order Ticket")
    actionable = [r for r in rows if r["action"] != "FLAT" and r["quarantine_until"] == "—"]
    if not actionable:
        st.info("Không có pair nào actionable hiện tại (z chưa breach entry hoặc đang quarantine)")
        return

    selected_pair = st.selectbox(
        "Chọn pair để generate ticket",
        options=[r["Pair"] for r in actionable],
    )
    if st.button("📝 Generate Order Ticket JSON"):
        chosen_row = next(r for r in actionable if r["Pair"] == selected_pair)
        t1, t2 = chosen_row["Pair"].split("/")
        side = +1 if "LONG SPREAD" in chosen_row["action"] else -1
        ticket = generate_order_ticket(
            t1=t1, t2=t2, side=side,
            beta=chosen_row["β"],
            price1=float(prices[t1].iloc[-1]),
            price2=float(prices[t2].iloc[-1]),
            capital=params["capital"],
            z_at_entry=chosen_row["z_now"],
            half_life=chosen_row["half_life"],
            stop_z=params["z_stop"],
        )
        ticket_json = order_ticket_to_json(ticket)
        st.code(ticket_json, language="json")
        st.download_button(
            "💾 Download JSON",
            data=ticket_json,
            file_name=f"order_ticket_{t1}_{t2}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
        )


# ─────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────


def render() -> None:
    st.title("🔁 Pairs Trading Research Lab")
    st.caption(
        "Cointegration + OU half-life + Z-score 60d signal trên VN cluster. "
        "Research dashboard — KHÔNG plug AI CIO synthesis (spec §13.5)."
    )

    prices = load_close_prices()
    params = render_sidebar(list(prices.columns))

    # Restrict to lookback window
    prices_window = _load_prices_for_pairs(params["lookback_years"])

    _show_global_warnings()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔍 Cluster Scan",
        "🗺️ Pairwise Heatmap",
        "🎯 Custom Pair",
        "📈 Aggregate Backtest",
        "🚦 Live Signals",
    ])
    with tab1:
        _tab_cluster_scan(prices_window, params)
    with tab2:
        _tab_pairwise(prices_window, params)
    with tab3:
        _tab_custom_pair(prices_window, params)
    with tab4:
        _tab_aggregate_backtest(prices_window, params)
    with tab5:
        _tab_live_signals(prices_window, params)
