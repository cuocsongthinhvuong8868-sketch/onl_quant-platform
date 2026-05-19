"""
page.py — Pairs Trading Streamlit page.

6 tabs:
  1. Cluster Scan         — Johansen + half-life + dominant spread
  2. Pairwise Heatmap     — NxN EG p-value matrix + current ρ heatmap
  3. Universe Scanner     — 4-stage funnel (sector → ρ → EG → half-life) → top candidate
  4. Custom Pair          — Full EG + OU + Hurst + z-score + DCC + 2yr backtest
  5. Backtest aggregate   — All cointegrated pair trong cluster
  6. Live Signals (P2)    — Current cointegrated pair với |z|, order ticket gen

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
from tools.pairs_trading.quant.dcc_filter import (
    cluster_rho_matrix,
    pair_rho_now,
    pair_rho_series,
    passes_rho_filter,
)
from tools.pairs_trading.quant.scanner import run_universe_scan
from tools.pairs_trading.ui.sidebar import render_sidebar
from tools.pairs_trading.ui.charts import (
    render_spread_chart,
    render_cluster_heatmap,
    render_backtest_equity,
    render_residual_diagnostics,
    render_pair_rho_chart,
    render_correlation_heatmap,
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

    # DCC current correlation heatmap (cheap EWMA path, luôn show side-by-side)
    rho_matrix = cluster_rho_matrix(sub, tickers)
    if not rho_matrix.empty:
        st.markdown("#### Current dynamic correlation (EWMA λ=0.94)")
        st.caption(
            "Pair có ρ cao + p-value EG thấp = ứng viên tốt nhất (cointegrated + co-moving). "
            "Pair ρ thấp dù EG pass = stale relationship, regime đã đổi."
        )
        st.plotly_chart(render_correlation_heatmap(rho_matrix), use_container_width=True)

    # Sort cointegrated pairs by p-value, thêm ρ column
    rows = []
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            if i < j:
                p = M.iloc[i, j]
                if pd.notna(p):
                    rho_val = (
                        float(rho_matrix.loc[t1, t2])
                        if not rho_matrix.empty
                        and t1 in rho_matrix.index
                        and t2 in rho_matrix.columns
                        else np.nan
                    )
                    rows.append({
                        "Pair": f"{t1}/{t2}",
                        "p_value": p,
                        "ρ_now": rho_val,
                        "Cointegrated": p < 0.05,
                    })
    if rows:
        df = pd.DataFrame(rows).sort_values("p_value")
        st.markdown("#### Ranked pairs (low p = strong cointegration, high ρ = co-moving)")
        st.dataframe(
            df.style.format({"p_value": "{:.4f}", "ρ_now": "{:.3f}"}),
            use_container_width=True, hide_index=True,
        )


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

    # Compute current ρ (EWMA path always — cheap)
    dcc_method = params.get("dcc_method", "ewma")
    rho_now = pair_rho_now(sub, t1, t2, method=dcc_method)

    # Metrics row (6 columns now, thêm ρ_now)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("β (hedge ratio)", f"{eg['beta']:.4f}")
    c2.metric("ADF p-value", f"{eg['p_value']:.4f}",
              delta="cointegrated" if eg["is_cointegrated"] else "NOT cointegrated",
              delta_color="normal" if eg["is_cointegrated"] else "inverse")
    c3.metric("Half-life (d)", f"{hl_raw:.1f}" if np.isfinite(hl_raw) else "NaN")
    c4.metric("Hurst", f"{h:.3f}", delta="mean-revert" if h < 0.5 else "drift",
              delta_color="normal" if h < 0.5 else "inverse")
    c5.metric("Z latest", f"{z_series.dropna().iloc[-1]:.2f}" if z_series.notna().any() else "—")
    if np.isfinite(rho_now):
        passes = passes_rho_filter(rho_now, params.get("min_rho", 0.5))
        c6.metric(
            f"ρ_now ({dcc_method.upper()})",
            f"{rho_now:.3f}",
            delta="≥ min ρ" if passes else "< min ρ (decoupling)",
            delta_color="normal" if passes else "inverse",
        )
    else:
        c6.metric(f"ρ_now ({dcc_method.upper()})", "NaN")

    # Spread chart
    st.plotly_chart(
        render_spread_chart(
            spread, z_series, sig,
            z_entry=params["z_entry"], z_stop=params["z_stop"],
            title=f"{t1}/{t2} spread & z-score",
        ),
        use_container_width=True,
    )

    # ρ_t time-series chart
    rho_ts = pair_rho_series(sub, t1, t2, method=dcc_method)
    if not rho_ts.dropna().empty:
        st.plotly_chart(
            render_pair_rho_chart(
                rho_ts.dropna(),
                min_rho=params.get("min_rho", 0.5),
                method=dcc_method,
                title=f"{t1}/{t2} dynamic correlation",
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

    use_dcc = params.get("use_dcc_filter", False)
    min_rho = params.get("min_rho", 0.5)
    dcc_method = params.get("dcc_method", "ewma")

    rows = []
    equity_curves = {}
    skipped_rho = 0
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
                rho_now = pair_rho_now(sub, t1, t2, method=dcc_method)
                if use_dcc and not passes_rho_filter(rho_now, min_rho):
                    skipped_rho += 1
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
                    "ρ_now": round(rho_now, 3) if np.isfinite(rho_now) else float("nan"),
                    "half_life": round(hl, 1),
                    "total_ret": stats["total_return"],
                    "sharpe": round(stats["sharpe"], 2),
                    "max_dd": round(stats["max_dd"], 4),
                    "n_trades": stats["n_trades"],
                })
                equity_curves[f"{t1}/{t2}"] = eq["equity"]
            except Exception as exc:
                logger.warning("Aggregate backtest fail %s/%s: %s", t1, t2, exc)

    if use_dcc and skipped_rho:
        st.caption(f"ℹ️ DCC filter active — skipped {skipped_rho} pair với ρ_now < {min_rho:.2f}")

    if not rows:
        filter_desc = (
            f"cointegrated + half-life ∈ [{params['hl_min']}, {params['hl_max']}]"
            + (f" + ρ ≥ {min_rho:.2f}" if use_dcc else "")
        )
        st.info(
            f"Không có pair nào pass filter ({filter_desc}). "
            "Thử relax filter trong sidebar."
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

    use_dcc = params.get("use_dcc_filter", False)
    min_rho = params.get("min_rho", 0.5)
    dcc_method = params.get("dcc_method", "ewma")

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
                rho_now = pair_rho_now(sub, t1, t2, method=dcc_method)
                rho_pass = passes_rho_filter(rho_now, min_rho)
                # ρ filter là HARD GATE cho action: nếu use_dcc=True và ρ<min → FLAT
                action = "FLAT"
                if not in_quarantine and (not use_dcc or rho_pass):
                    if z_last < -params["z_entry"]:
                        action = f"LONG SPREAD (long {t1}, short {t2})"
                    elif z_last > params["z_entry"]:
                        action = f"SHORT SPREAD (short {t1}, long {t2})"
                rows.append({
                    "Pair": f"{t1}/{t2}",
                    "β": round(eg["beta"], 4),
                    "z_now": round(z_last, 2),
                    "ρ_now": round(rho_now, 3) if np.isfinite(rho_now) else float("nan"),
                    "half_life": round(hl, 1),
                    "action": action,
                    "quarantine_until": quarantine.strftime("%Y-%m-%d") if in_quarantine else "—",
                    "_rho_pass": rho_pass,
                })
            except Exception as exc:
                logger.warning("Live signal fail %s/%s: %s", t1, t2, exc)

    if not rows:
        st.info(f"Không có pair nào qualify trong cluster {cluster_name}.")
        return

    df = pd.DataFrame(rows).sort_values("z_now", key=lambda s: s.abs(), ascending=False)
    if use_dcc:
        st.caption(
            f"ℹ️ DCC filter active: pair với ρ_now < {min_rho:.2f} ({dcc_method.upper()}) "
            f"force action = FLAT bất kể z."
        )
    # Drop internal flag column trước khi hiển thị
    st.dataframe(df.drop(columns=["_rho_pass"]), use_container_width=True, hide_index=True)

    # Order ticket generator — actionable phải pass cả quarantine VÀ ρ filter (nếu enabled)
    st.markdown("---")
    st.markdown("#### Generate Order Ticket")
    actionable = [
        r for r in rows
        if r["action"] != "FLAT" and r["quarantine_until"] == "—"
        and (not use_dcc or r["_rho_pass"])
    ]
    if not actionable:
        msg = "Không có pair nào actionable hiện tại (z chưa breach entry hoặc đang quarantine"
        if use_dcc:
            msg += f" hoặc ρ_now < {min_rho:.2f}"
        msg += ")"
        st.info(msg)
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
            rho_at_entry=chosen_row.get("ρ_now"),
            rho_method=dcc_method,
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
# Tab: Universe Scanner (sector → ρ → EG → half-life funnel)
# ─────────────────────────────────────────────────


@st.cache_data(ttl=3600, show_spinner=False)
def _run_universe_scan_cached(
    prices_hash: int,
    prices: pd.DataFrame,
    same_sector_only: bool,
    cross_exchange: bool,
    min_rho_screen: float,
    hl_min: int,
    hl_max: int,
) -> pd.DataFrame:
    """Cache key = (prices last-date hash + 5 filter params). TTL 1h."""
    return run_universe_scan(prices, {
        "same_sector_only": same_sector_only,
        "cross_exchange": cross_exchange,
        "min_rho_screen": min_rho_screen,
        "hl_min": hl_min,
        "hl_max": hl_max,
    })


def _tab_universe_scanner(prices: pd.DataFrame, params: dict) -> None:
    st.markdown("### 🔬 Universe Scanner")
    st.caption(
        f"Funnel 4-stage: **same-sector** → **ρ_60d ≥ {params['min_rho_screen']:.2f}** → "
        f"**EG p<0.05** → **half-life ∈ [{params['hl_min']}, {params['hl_max']}]**. "
        "Surface candidate từ ~245 mã universe, sau đó bạn validate sâu ở tab Custom Pair."
    )

    col_a, col_b, col_c = st.columns([1, 1, 3])
    with col_a:
        run = st.button("🔍 Run Scanner", type="primary", use_container_width=True)
    with col_b:
        clear = st.button(
            "🗑️ Clear",
            use_container_width=True,
            disabled="scanner_result" not in st.session_state,
        )
    with col_c:
        st.caption("Compute ~10-30s, cached 1h. Re-run khi đổi filter trong sidebar.")

    if clear:
        st.session_state.pop("scanner_result", None)
        st.session_state.pop("scanner_last_validated", None)
        st.rerun()

    if run:
        with st.spinner("Scanning ~245 mã universe (sector → ρ → EG → half-life)..."):
            try:
                prices_key = hash((str(prices.index[-1]), prices.shape))
                result = _run_universe_scan_cached(
                    prices_key, prices,
                    same_sector_only=params["same_sector_only"],
                    cross_exchange=params["cross_exchange"],
                    min_rho_screen=params["min_rho_screen"],
                    hl_min=params["hl_min"],
                    hl_max=params["hl_max"],
                )
                st.session_state["scanner_result"] = result
            except Exception as exc:
                st.error(f"Scanner fail: {exc}")
                logger.exception("Universe scan fail")
                return

    if "scanner_result" not in st.session_state:
        st.info(
            "👆 Click **'🔍 Run Scanner'** để bắt đầu funnel. "
            "Workflow: scanner surface ~5-20 candidate → click **'Pre-fill Custom Pair'** → "
            "switch sang tab **🎯 Custom Pair** để validate sâu (EG + OU + Hurst + DCC + backtest)."
        )
        return

    df = st.session_state["scanner_result"]

    if df.empty:
        st.warning(
            f"Không tìm thấy pair nào qualify với current params "
            f"(ρ_60d ≥ {params['min_rho_screen']:.2f}, "
            f"half-life ∈ [{params['hl_min']}, {params['hl_max']}]). "
            "Thử relax threshold trong sidebar và Run Scanner lại."
        )
        return

    st.success(
        f"✅ Surfaced **{len(df)}** candidate pair. "
        "Sorted by composite score = (1-p) × ρ × half_life_proximity_to_15. "
        "High score = strong cointegration + co-moving + reasonable mean-revert horizon."
    )

    # Display ranked table
    try:
        styled = (
            df.style
            .format({
                "ρ_60d": "{:.3f}",
                "p_value": "{:.4f}",
                "half_life": "{:.1f}",
                "beta": "{:.4f}",
                "score": "{:.4f}",
            })
            .background_gradient(subset=["score"], cmap="YlGn")
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Validate workflow
    st.markdown("---")
    st.markdown("#### 🎯 Validate candidate trong Custom Pair tab")
    col_pick, col_btn = st.columns([3, 1])
    with col_pick:
        selected = st.selectbox(
            "Chọn pair",
            options=df["pair"].tolist(),
            key="scanner_selected_pair",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("→ Pre-fill", type="primary", use_container_width=True):
            t1, t2 = selected.split("/")
            st.session_state["scanner_target_t1"] = t1
            st.session_state["scanner_target_t2"] = t2
            st.session_state["scanner_last_validated"] = f"{t1}/{t2}"
            st.rerun()

    if "scanner_last_validated" in st.session_state:
        st.info(
            f"📌 **{st.session_state['scanner_last_validated']}** đã pre-fill vào sidebar 'Custom pair'. "
            "Switch sang tab **🎯 Custom Pair** để validate sâu."
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

    # ── Handbook download (manual usage guide) ──
    from pathlib import Path as _Path
    _hb = _Path(__file__).resolve().parents[2] / "docs" / "pairs_trading_handbook.md"
    if _hb.exists():
        _c1, _c2 = st.columns([3, 1])
        with _c1:
            st.caption(
                "📖 **Manual Handbook** — hướng dẫn setup, đọc hiểu 5 tab, "
                "decision framework thủ công + cạm bẫy (Vingroup risk, FOL, T+2)."
            )
        with _c2:
            st.download_button(
                label="⬇️ Tải Handbook (.md)",
                data=_hb.read_bytes(),
                file_name="pairs_trading_handbook.md",
                mime="text/markdown",
                use_container_width=True,
                key="pairs_trading_handbook_dl",
            )

    prices = load_close_prices()
    params = render_sidebar(list(prices.columns))

    # Restrict to lookback window
    prices_window = _load_prices_for_pairs(params["lookback_years"])

    _show_global_warnings()

    tab1, tab2, tab_scan, tab3, tab4, tab5 = st.tabs([
        "🔍 Cluster Scan",
        "🗺️ Pairwise Heatmap",
        "🔬 Universe Scanner",
        "🎯 Custom Pair",
        "📈 Aggregate Backtest",
        "🚦 Live Signals",
    ])
    with tab1:
        _tab_cluster_scan(prices_window, params)
    with tab2:
        _tab_pairwise(prices_window, params)
    with tab_scan:
        _tab_universe_scanner(prices, params)
    with tab3:
        _tab_custom_pair(prices_window, params)
    with tab4:
        _tab_aggregate_backtest(prices_window, params)
    with tab5:
        _tab_live_signals(prices_window, params)
