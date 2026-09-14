"""Pairs Trading Research Lab — point-in-time methodology v2."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, replace
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import MARKET_DATA, MARKET_VOLUME
from shared.data_loader import load_close_prices, load_ticker_metadata, load_volumes
from tools.pairs_trading.quant.clusters import CLUSTER_DESCRIPTIONS, PREDEFINED_CLUSTERS
from tools.pairs_trading.quant.cointegration import (
    HALF_LIFE_MAX,
    HALF_LIFE_MIN,
    hurst,
    johansen_test,
    pairwise_eg_details,
)
from tools.pairs_trading.quant.data import (
    MarketDataSnapshot,
    assess_execution_readiness,
    build_market_data_snapshot,
)
from tools.pairs_trading.quant.engine import (
    PairAnalysisResult,
    PairResearchConfig,
    analyze_pair,
    walk_forward_backtest,
)
from tools.pairs_trading.quant.portfolio import aggregate_pair_backtests
from tools.pairs_trading.quant.scanner import run_universe_scan
from tools.pairs_trading.quant.signal import entry_exit_rules, quarantine_flag, z_score_60d
from tools.pairs_trading.quant.backtest import generate_order_ticket, order_ticket_to_json
from tools.pairs_trading.quant.dcc_filter import cluster_rho_matrix
from tools.pairs_trading.ui.charts import (
    render_backtest_equity,
    render_cluster_heatmap,
    render_correlation_heatmap,
    render_pair_rho_chart,
    render_residual_diagnostics,
    render_spread_chart,
)
from tools.pairs_trading.ui.sidebar import render_sidebar

logger = logging.getLogger(__name__)


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data(ttl=3600, show_spinner=False)
def _load_snapshot(
    price_mtime: int,
    volume_mtime: int,
    metadata_mtime: int,
) -> MarketDataSnapshot:
    del price_mtime, volume_mtime, metadata_mtime
    prices = load_close_prices()
    volumes = load_volumes()
    metadata = load_ticker_metadata()
    return build_market_data_snapshot(
        prices,
        volumes,
        metadata,
        adjusted_verified=False,
        point_in_time_universe=False,
        mask_stale_quotes_with_volume=True,
    )


def _config(params: dict, *, alpha: float = 0.05) -> PairResearchConfig:
    return PairResearchConfig(
        formation_window=params["formation_window"],
        refit_every=params["refit_every"],
        z_method=params["z_method"],
        entry_z=params["z_entry"],
        stop_z=params["z_stop"],
        hl_min=params["hl_min"],
        hl_max=params["hl_max"],
        min_rho=params["min_rho"],
        use_rho_filter=params["use_dcc_filter"],
        rho_method=params["dcc_method"],
        require_stability=params["require_stability"],
        hedge_method=params["hedge_method"],
        tc_bps_one_way=params["tc_bps"],
        sell_tax_bps=params["sell_tax_bps"],
        borrow_bps_annual=params["borrow_bps_annual"],
        alpha=alpha,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _walk_forward_cached(
    data_fingerprint: str,
    prices: pd.DataFrame,
    t1: str,
    t2: str,
    config_values: dict,
):
    del data_fingerprint
    return walk_forward_backtest(prices, t1, t2, PairResearchConfig(**config_values))


def _window(snapshot: MarketDataSnapshot, years: int) -> pd.DataFrame:
    start = snapshot.quality.as_of - pd.Timedelta(days=int(years * 365.25))
    return snapshot.prices.loc[start:]


def _quality_panel(snapshot: MarketDataSnapshot) -> None:
    quality = snapshot.quality
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Data as-of", quality.as_of.strftime("%Y-%m-%d"))
    c2.metric("Dataset", quality.fingerprint)
    c3.metric("Invalid prices removed", quality.nonpositive_cells_removed)
    c4.metric("Stale quotes masked", quality.volume_masked_cells)
    if quality.warnings:
        st.warning(" | ".join(quality.warnings))
    st.caption(
        "Live ticket is hard-gated until adjusted-price, borrow/shortability, FOL, "
        "liquidity, common quote and model-as-of checks all pass."
    )


def _cluster_prices(prices: pd.DataFrame, cluster: str) -> tuple[pd.DataFrame, list[str]]:
    tickers = [ticker for ticker in PREDEFINED_CLUSTERS[cluster] if ticker in prices]
    if len(tickers) < 2:
        raise ValueError("Cần >=2 ticker có dữ liệu trong cluster")
    return prices[tickers].dropna(how="any"), tickers


def _tab_cluster_scan(prices: pd.DataFrame, params: dict) -> None:
    cluster = params["cluster"]
    st.markdown(f"### Cluster: **{cluster}**")
    st.caption(CLUSTER_DESCRIPTIONS.get(cluster, ""))
    try:
        sub, tickers = _cluster_prices(prices, cluster)
        result = johansen_test(sub)
    except Exception as exc:
        st.error(f"Johansen không chạy được: {exc}")
        return
    trace = pd.DataFrame(
        {
            "H0: rank <=": range(len(tickers)),
            "Trace stat": result["trace_stat"],
            "Crit 95%": result["trace_crit_95"],
            "Reject": result["trace_stat"] > result["trace_crit_95"],
        }
    )
    st.dataframe(trace, width="stretch", hide_index=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Effective rank", result["n_coint_vectors"])
    c2.metric("Raw rank", result["raw_rank"])
    c3.metric("Selected Δ lags", result["k_ar_diff"])
    for warning in result["warnings"]:
        st.warning(warning)
    if result["n_coint_vectors"] < 1:
        st.info("Cluster không có cointegrating vector hợp lệ sau I(1)/full-rank guardrail.")
        return
    vector = result["eig_vectors"][:, 0]
    normalizer = vector[np.argmax(np.abs(vector))]
    normalized = vector / normalizer
    st.dataframe(
        pd.DataFrame({"Ticker": tickers, "Cointegrating weight": normalized}),
        width="stretch",
        hide_index=True,
    )
    spread = pd.Series(np.log(sub.to_numpy()) @ normalized, index=sub.index, name="spread")
    z = z_score_60d(spread, method=params["z_method"], lagged=True)
    half_life = float("nan")
    from tools.pairs_trading.quant.cointegration import ou_half_life_raw

    half_life = ou_half_life_raw(spread)
    signals = entry_exit_rules(
        z.dropna(),
        entry=params["z_entry"],
        stop=params["z_stop"],
        half_life=half_life,
    )
    c1, c2 = st.columns(2)
    c1.metric("OU half-life", f"{half_life:.1f}" if np.isfinite(half_life) else "—")
    c2.metric("Hurst", f"{hurst(spread):.3f}")
    if not np.isfinite(half_life) or not HALF_LIFE_MIN <= half_life <= HALF_LIFE_MAX:
        st.warning("Half-life ngoài execution band; chart chỉ dùng cho diagnostics.")
    st.plotly_chart(
        render_spread_chart(
            spread,
            z,
            signals,
            z_entry=params["z_entry"],
            z_stop=params["z_stop"],
            title=f"{cluster} Johansen spread",
        ),
        width="stretch",
    )


def _tab_pairwise(prices: pd.DataFrame, params: dict) -> None:
    cluster = params["cluster"]
    try:
        sub, tickers = _cluster_prices(prices, cluster)
        details = pairwise_eg_details(sub, tickers)
    except Exception as exc:
        st.error(f"Pairwise scan không chạy được: {exc}")
        return
    if details.empty:
        st.info("Không có pair đủ dữ liệu.")
        return
    q_matrix = pd.DataFrame(np.nan, index=tickers, columns=tickers)
    np.fill_diagonal(q_matrix.values, 0.0)
    for row in details.itertuples():
        q_matrix.loc[row.t1, row.t2] = row.q_value
        q_matrix.loc[row.t2, row.t1] = row.q_value
    st.markdown(f"### Pairwise Engle–Granger FDR — {cluster}")
    st.caption("Một orientation định trước cho mỗi pair; heatmap hiển thị q-value Benjamini–Hochberg.")
    st.plotly_chart(render_cluster_heatmap(q_matrix, threshold=0.05), width="stretch")
    rho_matrix = cluster_rho_matrix(sub, tickers)
    if not rho_matrix.empty:
        st.plotly_chart(render_correlation_heatmap(rho_matrix), width="stretch")
    table = details[
        ["orientation", "p_value", "q_value", "i1_valid", "fdr_cointegrated", "beta", "n_obs"]
    ].copy()
    table = table.rename(columns={"orientation": "Pair", "fdr_cointegrated": "FDR pass"})
    st.dataframe(
        table.sort_values("q_value"),
        width="stretch",
        hide_index=True,
        column_config={
            "p_value": st.column_config.NumberColumn(format="%.4f"),
            "q_value": st.column_config.NumberColumn(format="%.4f"),
            "beta": st.column_config.NumberColumn(format="%.4f"),
        },
    )


def _scanner_fingerprint(snapshot: MarketDataSnapshot, params: dict) -> str:
    payload = {
        "dataset": snapshot.quality.fingerprint,
        "same_sector_only": params["same_sector_only"],
        "cross_exchange": params["cross_exchange"],
        "min_rho_screen": params["min_rho_screen"],
        "hl_min": params["hl_min"],
        "hl_max": params["hl_max"],
        "formation_window": params["formation_window"],
        "min_adv_vnd": params["min_adv_vnd"],
        "require_stability": params["require_stability"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


@st.cache_data(ttl=3600, show_spinner=False)
def _run_scanner_cached(
    data_fingerprint: str,
    prices: pd.DataFrame,
    volumes: pd.DataFrame | None,
    metadata: pd.DataFrame | None,
    params_json: str,
) -> pd.DataFrame:
    del data_fingerprint
    return run_universe_scan(
        prices,
        json.loads(params_json),
        volumes=volumes,
        metadata=metadata,
    )


def _tab_universe_scanner(snapshot: MarketDataSnapshot, params: dict) -> None:
    st.markdown("### Universe Scanner v2")
    st.caption(
        "Sector/exchange → return correlation → proper EG + I(1) → BH-FDR → "
        "exact half-life → beta stability → ADV capacity."
    )
    fingerprint = _scanner_fingerprint(snapshot, params)
    scan_params = {
        "same_sector_only": params["same_sector_only"],
        "cross_exchange": params["cross_exchange"],
        "min_rho_screen": params["min_rho_screen"],
        "hl_min": params["hl_min"],
        "hl_max": params["hl_max"],
        "formation_window": params["formation_window"],
        "min_adv_vnd": params["min_adv_vnd"],
        "require_stability": params["require_stability"],
        "alpha": 0.05,
    }
    c1, c2 = st.columns([1, 4])
    run = c1.button("Run scanner", type="primary", width="stretch")
    c2.caption(f"Cache key {fingerprint}; tự stale khi data hoặc filter đổi.")
    if run:
        try:
            with st.spinner("Scanning point-in-time universe..."):
                result = _run_scanner_cached(
                    snapshot.quality.fingerprint,
                    snapshot.prices,
                    snapshot.volumes,
                    snapshot.metadata,
                    json.dumps(scan_params, sort_keys=True),
                )
            st.session_state["pairs_scanner_result"] = result
            st.session_state["pairs_scanner_fingerprint"] = fingerprint
        except Exception as exc:
            st.error(f"Scanner failed: {exc}")
            logger.exception("Pairs scanner failed")
            return
    result = st.session_state.get("pairs_scanner_result")
    stored_fingerprint = st.session_state.get("pairs_scanner_fingerprint")
    if result is None:
        st.info("Bấm Run scanner để tạo candidate set.")
        return
    if stored_fingerprint != fingerprint:
        st.warning("Kết quả cũ không khớp data/filter hiện tại; hãy chạy lại scanner.")
        return
    funnel = result.attrs.get("funnel", {})
    if funnel:
        st.json(funnel, expanded=False)
    if result.empty:
        st.info("Không có pair pass toàn bộ statistical, stability và liquidity gates.")
        return
    st.dataframe(
        result,
        width="stretch",
        hide_index=True,
        column_config={
            "p_value": st.column_config.NumberColumn(format="%.4f"),
            "q_value": st.column_config.NumberColumn(format="%.4f"),
            "min_adv_vnd": st.column_config.NumberColumn(format="%.0f"),
            "score": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0),
        },
    )
    selected = st.selectbox("Candidate để đưa sang Custom Pair", result["pair"].tolist())
    if st.button("Pre-fill Custom Pair"):
        t1, t2 = selected.split("/")
        st.session_state["scanner_target_t1"] = t1
        st.session_state["scanner_target_t2"] = t2
        st.rerun()


def _static_signal(result: PairAnalysisResult, params: dict) -> pd.DataFrame:
    gate = pd.Series(result.eligible, index=result.z_score.index)
    return entry_exit_rules(
        result.z_score.dropna(),
        entry=params["z_entry"],
        stop=params["z_stop"],
        half_life=result.half_life,
        eligible=gate,
        quarantine_bars=60,
    )


def _tab_custom_pair(prices: pd.DataFrame, params: dict) -> None:
    t1, t2 = params["custom_t1"], params["custom_t2"]
    st.markdown(f"### Custom pair: **{t1}/{t2}**")
    try:
        result = analyze_pair(prices, t1, t2, _config(params))
    except Exception as exc:
        st.error(f"Pair analysis failed: {exc}")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Beta", f"{result.beta:.4f}")
    c2.metric("EG p/q", f"{result.p_value:.4f}")
    c3.metric("Half-life", f"{result.half_life:.1f}" if np.isfinite(result.half_life) else "—")
    c4.metric("Z now", f"{result.z_latest:.2f}" if np.isfinite(result.z_latest) else "—")
    c5.metric("Stability", f"{result.stability_score:.0%}")
    if result.eligible:
        st.success("Current formation window passes the configured research gates.")
    else:
        st.warning("Diagnostic only — blocked by: " + ", ".join(result.eligibility_reasons))
    for warning in result.warnings:
        st.caption(f"Warning: {warning}")
    signals = _static_signal(result, params)
    st.plotly_chart(
        render_spread_chart(
            result.spread,
            result.z_score,
            signals,
            z_entry=params["z_entry"],
            z_stop=params["z_stop"],
            title=f"{result.pair} static formation diagnostics",
        ),
        width="stretch",
    )
    if not result.rho_series.dropna().empty:
        st.plotly_chart(
            render_pair_rho_chart(
                result.rho_series.dropna(),
                min_rho=params["min_rho"],
                method=result.rho_method_actual,
                title=f"{result.pair} correlation ({result.rho_method_actual.upper()})",
            ),
            width="stretch",
        )
    with st.expander("Residual and model diagnostics"):
        st.plotly_chart(
            render_residual_diagnostics(result.spread, result.coint_stat, result.p_value),
            width="stretch",
        )
        st.json(result.to_record(), expanded=False)

    st.markdown("#### Walk-forward out-of-sample backtest")
    try:
        cfg = _config(params)
        wf = _walk_forward_cached(
            f"{prices.index[-1]}-{prices.shape}",
            prices,
            t1,
            t2,
            asdict(cfg),
        )
    except Exception as exc:
        st.info(f"Walk-forward unavailable: {exc}")
        return
    stats = wf.stats
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Net return", f"{stats['total_return']:.1%}")
    m2.metric("Sharpe", f"{stats['sharpe']:.2f}")
    m3.metric("Max DD", f"{stats['max_dd']:.1%}")
    m4.metric("Trade win rate", f"{stats['win_rate']:.1%}" if np.isfinite(stats["win_rate"]) else "—")
    m5.metric("Completed trades", stats["n_trades"])
    st.plotly_chart(render_backtest_equity(wf.equity), width="stretch")
    with st.expander("Trade ledger / point-in-time refits"):
        st.dataframe(wf.ledger, width="stretch", hide_index=True)
        st.dataframe(wf.refits, width="stretch", hide_index=True)


def _tab_aggregate_backtest(
    snapshot: MarketDataSnapshot,
    prices: pd.DataFrame,
    params: dict,
) -> None:
    cluster = params["cluster"]
    try:
        _, tickers = _cluster_prices(prices, cluster)
    except Exception as exc:
        st.error(str(exc))
        return
    pairs = list(combinations(tickers, 2))
    family_alpha = 0.05 / max(1, len(pairs))
    cfg = _config(params, alpha=family_alpha)
    st.markdown(f"### Walk-forward portfolio — {cluster}")
    st.caption(
        f"{len(pairs)} pair, family-wise alpha={family_alpha:.4f}, fixed ex-ante pair allocation, "
        "shared ticker exposures are netted."
    )
    rows: list[dict] = []
    curves: dict[str, pd.DataFrame] = {}
    failures: list[str] = []
    with st.spinner("Running point-in-time pair refits and portfolio aggregation..."):
        for t1, t2 in pairs:
            name = f"{t1}/{t2}"
            try:
                wf = _walk_forward_cached(
                    snapshot.quality.fingerprint,
                    prices,
                    t1,
                    t2,
                    asdict(cfg),
                )
                eligible_refits = (
                    float(wf.refits["eligible"].fillna(False).mean())
                    if not wf.refits.empty and "eligible" in wf.refits
                    else 0.0
                )
                rows.append(
                    {
                        "Pair": name,
                        "net_return": wf.stats["total_return"],
                        "sharpe": wf.stats["sharpe"],
                        "max_dd": wf.stats["max_dd"],
                        "win_rate": wf.stats["win_rate"],
                        "trades": wf.stats["n_trades"],
                        "eligible_refits": eligible_refits,
                        "cost_drag": wf.stats["cost_drag"],
                    }
                )
                # Keep every successfully specified pair in the ex-ante book.
                # Excluding a pair because it happened not to trade in the full
                # sample would use future outcomes to reallocate its cash weight.
                curves[name] = wf.equity
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}")
    if not rows:
        st.info("Không có pair đủ lịch sử cho walk-forward.")
        return
    st.dataframe(
        pd.DataFrame(rows).sort_values("sharpe", ascending=False),
        width="stretch",
        hide_index=True,
        column_config={
            "net_return": st.column_config.NumberColumn(format="percent"),
            "max_dd": st.column_config.NumberColumn(format="percent"),
            "win_rate": st.column_config.NumberColumn(format="percent"),
            "eligible_refits": st.column_config.NumberColumn(format="percent"),
        },
    )
    if failures:
        st.caption("Fit failures: " + "; ".join(failures))
    if not curves:
        st.info("Không có pair nào fit được cho portfolio walk-forward.")
        return
    portfolio = aggregate_pair_backtests(
        curves,
        max_pair_weight=params["max_pair_weight"],
        tc_bps_one_way=params["tc_bps"],
        sell_tax_bps=params["sell_tax_bps"],
        borrow_bps_annual=params["borrow_bps_annual"],
    )
    s = portfolio.stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio net return", f"{s['total_return']:.1%}")
    c2.metric("Portfolio Sharpe", f"{s['sharpe']:.2f}")
    c3.metric("Portfolio max DD", f"{s['max_dd']:.1%}")
    c4.metric("Max gross exposure", f"{s['gross_exposure_max']:.1%}")
    st.plotly_chart(
        render_backtest_equity(portfolio.equity, title=f"{cluster} walk-forward portfolio"),
        width="stretch",
    )
    with st.expander("Allocation and netted ticker exposure"):
        st.dataframe(
            portfolio.pair_weights.rename("weight").to_frame(),
            width="stretch",
        )
        st.dataframe(
            portfolio.latest_ticker_exposure.rename("latest_exposure").to_frame(),
            width="stretch",
        )


def _current_cluster_results(
    prices: pd.DataFrame,
    params: dict,
) -> list[PairAnalysisResult]:
    _, tickers = _cluster_prices(prices, params["cluster"])
    formation = prices[tickers].dropna(how="all").tail(params["formation_window"])
    details = pairwise_eg_details(formation, tickers)
    q_map = {
        (row.t1, row.t2): float(row.q_value)
        for row in details.itertuples()
    }
    results: list[PairAnalysisResult] = []
    for t1, t2 in combinations(tickers, 2):
        try:
            results.append(
                analyze_pair(
                    prices,
                    t1,
                    t2,
                    _config(params),
                    q_value=q_map.get((t1, t2), float("nan")),
                )
            )
        except Exception as exc:
            logger.warning("Live pair analysis failed %s/%s: %s", t1, t2, exc)
    return results


def _tab_live_signals(
    snapshot: MarketDataSnapshot,
    prices: pd.DataFrame,
    params: dict,
) -> None:
    st.markdown(f"### Current signals — {params['cluster']}")
    st.caption(
        "Signal eligibility uses proper EG + I(1) + cluster-level BH-FDR + half-life "
        "+ optional stability/rho gates. Ticket eligibility adds execution checks."
    )
    try:
        results = _current_cluster_results(prices, params)
    except Exception as exc:
        st.error(f"Live analysis failed: {exc}")
        return
    rows: list[dict] = []
    result_map: dict[str, PairAnalysisResult] = {}
    readiness_map = {}
    for result in results:
        result_map[result.pair] = result
        quarantine_until = quarantine_flag(
            result.z_score,
            stop=params["z_stop"],
            days=60,
        )
        in_quarantine = bool(
            quarantine_until is not None
            and quarantine_until > snapshot.quality.as_of
        )
        readiness = assess_execution_readiness(
            snapshot,
            result.t1,
            result.t2,
            model_as_of=result.as_of,
            adjusted_override=params["adjusted_verified"],
            borrow_confirmed=params["borrow_confirmed"],
            foreign_room_verified=params["foreign_room_verified"],
            shortable=params["shortable"],
            min_adv_vnd=params["min_adv_vnd"],
        )
        readiness_map[result.pair] = readiness
        signal = "MONITOR"
        if in_quarantine:
            signal = "QUARANTINE"
        elif not result.eligible:
            signal = "RESEARCH_BLOCKED"
        elif np.isfinite(result.z_latest) and -params["z_stop"] < result.z_latest <= -params["z_entry"]:
            signal = "ENTRY_LONG_SPREAD"
        elif np.isfinite(result.z_latest) and params["z_entry"] <= result.z_latest < params["z_stop"]:
            signal = "ENTRY_SHORT_SPREAD"
        ticket_status = (
            "READY"
            if signal.startswith("ENTRY_") and readiness.ready
            else "BLOCKED" if signal.startswith("ENTRY_") else "N/A"
        )
        rows.append(
            {
                "Pair": result.pair,
                "p_value": result.p_value,
                "q_value": result.q_value,
                "beta": result.beta,
                "half_life": result.half_life,
                "z_now": result.z_latest,
                "rho_now": result.rho_now,
                "stability": result.stability_score,
                "signal": signal,
                "ticket": ticket_status,
                "reason": (
                    ", ".join(result.eligibility_reasons)
                    if result.eligibility_reasons
                    else "; ".join(readiness.reasons) if signal.startswith("ENTRY_") and not readiness.ready
                    else ""
                ),
                "quarantine_until": (
                    quarantine_until.strftime("%Y-%m-%d") if in_quarantine else ""
                ),
            }
        )
    if not rows:
        st.info("Không có pair đủ dữ liệu.")
        return
    table = pd.DataFrame(rows).sort_values("z_now", key=lambda values: values.abs(), ascending=False)
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "p_value": st.column_config.NumberColumn(format="%.4f"),
            "q_value": st.column_config.NumberColumn(format="%.4f"),
            "z_now": st.column_config.NumberColumn(format="%.2f"),
            "rho_now": st.column_config.NumberColumn(format="%.3f"),
            "stability": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0),
        },
    )
    ready_pairs = [
        row["Pair"]
        for row in rows
        if row["signal"].startswith("ENTRY_") and readiness_map[row["Pair"]].ready
    ]
    if not ready_pairs:
        st.info(
            "Không có ticket đủ điều kiện. Entry research vẫn hiển thị nhưng download bị khóa "
            "cho tới khi mọi execution check pass."
        )
        return
    selected = st.selectbox("Pair đủ điều kiện tạo ticket", ready_pairs)
    if st.button("Generate audited research ticket", type="primary"):
        result = result_map[selected]
        readiness = readiness_map[selected]
        pair_prices = snapshot.pair_prices(result.t1, result.t2)
        last_quote = pair_prices.iloc[-1]
        side = 1 if result.z_latest < 0 else -1
        try:
            ticket = generate_order_ticket(
                result.t1,
                result.t2,
                side,
                result.beta,
                float(last_quote[result.t1]) * 1_000,
                float(last_quote[result.t2]) * 1_000,
                params["capital"] * 1_000,
                result.z_latest,
                result.half_life,
                stop_z=params["z_stop"],
                rho_at_entry=result.rho_now,
                rho_method=result.rho_method_actual,
                data_as_of=readiness.data_as_of,
                model_as_of=result.as_of.strftime("%Y-%m-%d"),
                adjusted_verified=params["adjusted_verified"],
                borrow_confirmed=params["borrow_confirmed"],
                foreign_room_verified=params["foreign_room_verified"],
                shortable=params["shortable"],
                execution_checks=readiness.checks,
                require_execution_checks=True,
            )
            payload = order_ticket_to_json(ticket)
        except Exception as exc:
            st.error(f"Ticket rejected: {exc}")
            return
        st.code(payload, language="json")
        st.download_button(
            "Download JSON",
            payload,
            file_name=f"pair_ticket_{result.t1}_{result.t2}_{datetime.now():%Y%m%d_%H%M%S}.json",
            mime="application/json",
        )


def render() -> None:
    st.title("Pairs Trading Research Lab v2")
    st.caption(
        "Proper Engle–Granger/FDR, causal signals, walk-forward backtests, "
        "portfolio exposure netting and audited execution gates."
    )
    handbook = Path(__file__).resolve().parents[2] / "docs" / "pairs_trading_handbook.md"
    if handbook.exists():
        st.download_button(
            "Download handbook",
            handbook.read_bytes(),
            file_name="pairs_trading_handbook.md",
            mime="text/markdown",
        )
    try:
        snapshot = _load_snapshot(
            _mtime(MARKET_DATA),
            _mtime(MARKET_VOLUME),
            _mtime(Path("data_lake/ticker_metadata.csv")),
        )
    except Exception as exc:
        st.error(f"Không tải được market snapshot: {exc}")
        return
    params = render_sidebar(list(snapshot.prices.columns))
    prices = _window(snapshot, params["lookback_years"])
    _quality_panel(snapshot)

    labels = [
        "Cluster Scan",
        "Pairwise FDR",
        "Universe Scanner",
        "Custom Pair",
        "Portfolio Backtest",
        "Live Signals",
    ]
    tabs = st.tabs(labels, key="pairs_active_tab", on_change="rerun")
    handlers = [
        lambda: _tab_cluster_scan(prices, params),
        lambda: _tab_pairwise(prices, params),
        lambda: _tab_universe_scanner(snapshot, params),
        lambda: _tab_custom_pair(prices, params),
        lambda: _tab_aggregate_backtest(snapshot, prices, params),
        lambda: _tab_live_signals(snapshot, prices, params),
    ]
    for tab, handler in zip(tabs, handlers):
        if tab.open:
            with tab:
                handler()
