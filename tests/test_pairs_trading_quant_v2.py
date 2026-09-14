from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from tools.pairs_trading.quant.backtest import (
    basket_pnl,
    generate_order_ticket,
    order_ticket_to_json,
    summary_stats,
    trade_ledger,
)
from tools.pairs_trading.quant.cointegration import (
    adjust_pvalues_fdr,
    engle_granger,
    kalman_hedge_ratio,
    ou_half_life_diagnostics,
    rolling_hedge_ratio,
)
from tools.pairs_trading.quant.data import (
    assess_execution_readiness,
    build_market_data_snapshot,
)
from tools.pairs_trading.quant.engine import (
    PairResearchConfig,
    analyze_pair,
    walk_forward_backtest,
)
from tools.pairs_trading.quant.dcc_filter import pair_rho_series
from tools.pairs_trading.quant.portfolio import aggregate_pair_backtests
from tools.pairs_trading.quant import scanner
from tools.pairs_trading.quant.signal import entry_exit_rules


def _cointegrated_prices(periods: int = 700, seed: int = 123) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-02", periods=periods, freq="B")
    common = 4.0 + np.cumsum(rng.normal(0, 0.012, periods))
    noise = np.zeros(periods)
    for i in range(1, periods):
        noise[i] = 0.75 * noise[i - 1] + rng.normal(0, 0.006)
    return pd.DataFrame(
        {"AAA": np.exp(0.2 + 1.15 * common + noise), "BBB": np.exp(common)},
        index=index,
    )


def test_engle_granger_uses_cointegration_distribution_and_i1_gate() -> None:
    prices = _cointegrated_prices()
    result = engle_granger(prices["AAA"], prices["BBB"])

    assert result["methodology_version"] == "engle_granger_mackinnon_i1_v2"
    assert result["i1_valid"] is True
    assert result["is_cointegrated"] is True
    assert result["p_value"] < 0.05
    assert result["beta"] == pytest.approx(1.15, abs=0.08)


def test_canonical_analysis_exposes_auditable_model_fields() -> None:
    prices = _cointegrated_prices()
    result = analyze_pair(
        prices,
        "AAA",
        "BBB",
        PairResearchConfig(formation_window=504, hl_min=1, hl_max=200),
        q_value=0.01,
    )
    record = result.to_record()

    assert result.as_of == prices.index[-1]
    assert result.n_obs == 504
    assert record["coint_stat"] == result.coint_stat
    assert record["q_value"] == 0.01
    assert record["methodology_version"] == "pairs_research_point_in_time_v2"


def test_fdr_controls_multiple_pair_decisions() -> None:
    rejected, q_values = adjust_pvalues_fdr([0.001, 0.02, 0.04, 0.8], alpha=0.05)

    assert rejected.tolist() == [True, True, False, False]
    assert np.all(np.diff(q_values) >= 0)


def test_exact_ar1_half_life_is_recovered() -> None:
    rng = np.random.default_rng(7)
    phi = 0.8
    values = np.zeros(3_000)
    for i in range(1, len(values)):
        values[i] = 0.4 + phi * values[i - 1] + rng.normal(0, 0.2)
    result = ou_half_life_diagnostics(pd.Series(values))

    assert result["phi"] == pytest.approx(phi, abs=0.03)
    assert result["half_life"] == pytest.approx(-np.log(2) / np.log(phi), rel=0.15)
    assert result["ci_low"] < result["half_life"] < result["ci_high"]


def test_ewma_rho_history_is_invariant_to_appended_future_data() -> None:
    prices = _cointegrated_prices(500)
    short = pair_rho_series(prices.iloc[:350], "AAA", "BBB", method="ewma")
    full = pair_rho_series(prices, "AAA", "BBB", method="ewma")

    assert_series_equal(short, full.reindex(short.index))


@pytest.mark.parametrize("estimator", [rolling_hedge_ratio, kalman_hedge_ratio])
def test_dynamic_beta_challengers_are_causal(estimator) -> None:
    prices = _cointegrated_prices(500)
    short = estimator(prices.iloc[:350]["AAA"], prices.iloc[:350]["BBB"])
    full = estimator(prices["AAA"], prices["BBB"])

    assert_series_equal(short, full.reindex(short.index))


def test_stop_is_processed_before_entry_and_quarantine_is_session_based() -> None:
    index = pd.date_range("2026-01-01", periods=65, freq="B")
    z = pd.Series([-3.5, -3.4, -2.5] + [0.1] * 58 + [-2.5, -2.5, 0.1, 0.1], index=index)
    signals = entry_exit_rules(z, entry=2.0, stop=3.0, quarantine_bars=60)

    assert signals.iloc[0]["event"] == "breakdown"
    assert (signals.iloc[:62]["position"] == 0).all()
    assert signals.iloc[62]["position"] == 1


def test_basket_pnl_charges_opening_cost_and_is_gross_normalized() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="B")
    prices = pd.DataFrame({"AAA": [100, 102, 104, 104], "BBB": [100, 100, 100, 100]}, index=index)
    signals = pd.DataFrame({"position": [1, 1, 1, 0]}, index=index)
    curve = basket_pnl(
        prices,
        beta=1.0,
        signals=signals,
        t1="AAA",
        t2="BBB",
        tc_bps=10,
        sell_tax_bps=0,
    )

    assert curve.iloc[0]["turnover"] == pytest.approx(1.0)
    assert curve.iloc[0]["execution_cost"] == pytest.approx(0.001)
    assert curve.iloc[1]["ret_gross"] == pytest.approx(0.5 * 0.02)
    assert curve.iloc[-1]["turnover"] == pytest.approx(1.0)
    ledger = trade_ledger(curve)
    stats = summary_stats(curve)
    assert len(ledger) == 1
    assert stats["n_trades"] == 1
    assert stats["win_rate"] == float(ledger.iloc[0]["net_return"] > 0)


def test_walk_forward_history_is_invariant_to_appended_future_data() -> None:
    prices = _cointegrated_prices()
    cfg = PairResearchConfig(
        formation_window=252,
        refit_every=20,
        hl_min=1,
        hl_max=200,
        entry_z=1.5,
        stop_z=4.0,
    )
    short = walk_forward_backtest(prices.iloc[:580], "AAA", "BBB", cfg)
    full = walk_forward_backtest(prices, "AAA", "BBB", cfg)
    common = short.signals.index[:-1]

    assert_series_equal(short.signals.loc[common, "z_score"], full.signals.loc[common, "z_score"])
    assert_series_equal(short.signals.loc[common, "position"], full.signals.loc[common, "position"])
    assert_series_equal(short.equity.loc[common, "ret_net"], full.equity.loc[common, "ret_net"])


def test_execution_gate_and_strict_ticket_contract() -> None:
    prices = _cointegrated_prices(300)
    volumes = pd.DataFrame(1_000_000.0, index=prices.index, columns=prices.columns)
    snapshot = build_market_data_snapshot(prices, volumes, adjusted_verified=True)
    readiness = assess_execution_readiness(
        snapshot,
        "AAA",
        "BBB",
        model_as_of=snapshot.quality.as_of,
        borrow_confirmed=True,
        foreign_room_verified=True,
        shortable=True,
        min_adv_vnd=1,
        max_data_age_sessions=10_000,
    )
    assert readiness.ready is True

    ticket = generate_order_ticket(
        "AAA",
        "BBB",
        1,
        1.0,
        10_000,
        10_000,
        100_000_000,
        -2.2,
        10,
        data_as_of=readiness.data_as_of,
        model_as_of=readiness.data_as_of,
        adjusted_verified=True,
        borrow_confirmed=True,
        foreign_room_verified=True,
        shortable=True,
        execution_checks=readiness.checks,
        require_execution_checks=True,
    )
    assert ticket["schema_version"] == "pair_order_ticket_v2"
    assert "+07:00" in ticket["timestamp"]
    assert '"schema_version": "pair_order_ticket_v2"' in order_ticket_to_json(ticket)

    with pytest.raises(ValueError, match="liquidity_ok"):
        generate_order_ticket(
            "AAA", "BBB", 1, 1.0, 10_000, 10_000, 100_000_000, -2.2, 10,
            data_as_of=readiness.data_as_of,
            model_as_of=readiness.data_as_of,
            adjusted_verified=True,
            borrow_confirmed=True,
            foreign_room_verified=True,
            shortable=True,
            execution_checks={**readiness.checks, "liquidity_ok": False},
            require_execution_checks=True,
        )


def test_snapshot_fingerprint_covers_historical_prices_volume_and_metadata() -> None:
    prices = _cointegrated_prices(300)
    volumes = pd.DataFrame(1_000_000.0, index=prices.index, columns=prices.columns)
    metadata = pd.DataFrame({"exchange": ["HOSE", "HOSE"]}, index=prices.columns)
    original = build_market_data_snapshot(prices, volumes, metadata)

    revised_prices = prices.copy()
    revised_prices.iloc[10, 0] *= 1.01
    revised_volumes = volumes.copy()
    revised_volumes.iloc[20, 1] += 1
    revised_metadata = metadata.copy()
    revised_metadata.loc["AAA", "exchange"] = "HNX"

    assert build_market_data_snapshot(revised_prices, volumes, metadata).quality.fingerprint != original.quality.fingerprint
    assert build_market_data_snapshot(prices, revised_volumes, metadata).quality.fingerprint != original.quality.fingerprint
    assert build_market_data_snapshot(prices, volumes, revised_metadata).quality.fingerprint != original.quality.fingerprint


def test_portfolio_backtest_nets_shared_ticker_exposure() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="B")
    first = pd.DataFrame(
        {"ret_gross": [0.0, 0.01, 0.0], "weight_1": [0.5, 0.5, 0], "weight_2": [-0.5, -0.5, 0]},
        index=index,
    )
    second = pd.DataFrame(
        {"ret_gross": [0.0, 0.02, 0.0], "weight_1": [0.5, 0.5, 0], "weight_2": [-0.5, -0.5, 0]},
        index=index,
    )
    result = aggregate_pair_backtests(
        {"AAA/BBB": first, "BBB/CCC": second},
        max_pair_weight=0.5,
        tc_bps_one_way=10,
    )

    assert result.pair_weights.sum() == pytest.approx(1.0)
    assert result.ticker_exposures.loc[index[1], "BBB"] == pytest.approx(0.0)
    assert result.equity.loc[index[0], "turnover"] == pytest.approx(0.5)
    assert result.equity.loc[index[1], "ret_gross"] == pytest.approx(0.015)
    assert result.equity.loc[index[1], "ret_net"] == pytest.approx(0.015)


def test_universe_scanner_applies_fdr_and_preserves_funnel(monkeypatch) -> None:
    rng = np.random.default_rng(19)
    index = pd.date_range("2025-01-02", periods=180, freq="B")
    common = np.cumsum(rng.normal(0, 0.01, len(index)))
    prices = pd.DataFrame(
        {
            ticker: np.exp(4 + common + rng.normal(0, 0.001, len(index)))
            for ticker in ("AAA", "BBB", "CCC")
        },
        index=index,
    )
    metadata = pd.DataFrame(
        {
            "industry_code": [1, 1, 1],
            "industry_name": ["Test", "Test", "Test"],
            "exchange": ["HOSE", "HOSE", "HOSE"],
        },
        index=["AAA", "BBB", "CCC"],
    )
    p_values = {
        frozenset(("AAA", "BBB")): 0.01,
        frozenset(("AAA", "CCC")): 0.04,
        frozenset(("BBB", "CCC")): 0.80,
    }

    def fake_eg(p1, p2, *, alpha=0.05):
        return {
            "p_value": p_values[frozenset((p1.name, p2.name))],
            "i1_valid": True,
            "beta": 1.0,
            "resid": pd.Series(0.0, index=p1.index),
            "n_obs": len(p1),
        }

    monkeypatch.setattr(scanner, "load_ticker_metadata", lambda: metadata)
    monkeypatch.setattr(
        scanner,
        "load_volumes",
        lambda: pd.DataFrame(1_000_000.0, index=index, columns=prices.columns),
    )
    monkeypatch.setattr(scanner, "engle_granger", fake_eg)
    monkeypatch.setattr(scanner, "ou_half_life_raw", lambda residual: 10.0)
    monkeypatch.setattr(
        scanner,
        "beta_stability",
        lambda *args, **kwargs: {"score": 0.9, "stable": True},
    )
    result = scanner.run_universe_scan(
        prices,
        {
            "min_rho_screen": 0.5,
            "hl_min": 5,
            "hl_max": 30,
            "formation_window": 180,
            "min_adv_vnd": 1,
            "require_stability": True,
        },
    )

    assert result["pair"].tolist() == ["AAA/BBB"]
    assert result.iloc[0]["q_value"] == pytest.approx(0.03)
    assert result.attrs["funnel"]["tested"] == 3
    assert result.attrs["funnel"]["fdr_pass"] == 1
