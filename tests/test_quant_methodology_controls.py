from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from tools.fear_greed.quant.factors import extract_market_factor_pca
from tools.global_financial_conditions.quant.metrics import (
    PCA_COLUMNS,
    _LABEL,
    fit_expanding_pca,
)
from tools.pairs_trading.quant.backtest import generate_order_ticket
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc
from tools.var_cvar_vnindex.quant.evt import evt_posterior_intervals, evt_threshold_sensitivity


def test_fear_greed_pca_is_invariant_to_appended_future_data() -> None:
    rng = np.random.default_rng(7)
    index = pd.date_range("2025-01-01", periods=150, freq="B")
    market = rng.normal(0, 0.01, len(index))
    returns = pd.DataFrame(
        {
            f"T{i}": market * (0.7 + i * 0.05) + rng.normal(0, 0.005, len(index))
            for i in range(8)
        },
        index=index,
    )

    short = extract_market_factor_pca(returns.iloc[:120], min_train=40, refit_every=10)
    full = extract_market_factor_pca(returns, min_train=40, refit_every=10)

    assert short.notna().sum() > 0
    assert_series_equal(short, full.iloc[:120], check_names=True)


def test_gfcm_pca_is_invariant_to_appended_future_data() -> None:
    rng = np.random.default_rng(11)
    index = pd.date_range("2025-01-01", periods=160, freq="B")
    common = rng.normal(size=len(index))
    z_cols = [f"{_LABEL[column]}_z" for column in PCA_COLUMNS]
    frame = pd.DataFrame(
        {
            column: common * (0.5 + i * 0.08) + rng.normal(scale=0.6, size=len(index))
            for i, column in enumerate(z_cols)
        },
        index=index,
    )

    short, _ = fit_expanding_pca(frame.iloc[:125], min_pca_samples=40, refit_every=10)
    full, meta = fit_expanding_pca(frame, min_pca_samples=40, refit_every=10)

    assert short["PC1"].notna().sum() > 0
    assert_frame_equal(short, full.iloc[:125])
    assert meta["pca_method"] == "expanding_point_in_time"


def test_pairs_ticket_sizes_leg_notionals_to_beta() -> None:
    ticket = generate_order_ticket(
        t1="AAA",
        t2="BBB",
        side=1,
        beta=2.0,
        price1=10_000,
        price2=10_000,
        capital=100_000_000,
        z_at_entry=-2.1,
        half_life=10,
    )

    assert ticket["notional_vnd"] <= 100_000_000
    assert ticket["realized_notional_hedge_ratio"] == 2.0
    assert ticket["hedge_ratio_error_pct"] == 0.0
    assert ticket["legs"][1]["quantity"] == 2 * ticket["legs"][0]["quantity"]


def test_upside_ratio_monte_carlo_seed_is_reproducible() -> None:
    series = pd.Series(np.linspace(10, 35, 40) + np.sin(np.arange(40)))

    first = run_hybrid_ensemble_mc(series, days_to_sim=6, num_sims=300, seed=123)
    second = run_hybrid_ensemble_mc(series, days_to_sim=6, num_sims=300, seed=123)
    different = run_hybrid_ensemble_mc(series, days_to_sim=6, num_sims=300, seed=124)

    for left, right in zip(first[:5], second[:5]):
        np.testing.assert_array_equal(left, right)
    assert not np.array_equal(first[2], different[2])


def test_evt_threshold_sensitivity_reports_robustness_grid() -> None:
    rng = np.random.default_rng(99)
    returns = pd.Series(rng.standard_t(df=4, size=1_000) * 0.01)

    result = evt_threshold_sensitivity(returns)
    valid = result[result["status"] == "ok"]

    assert result["threshold_pct"].tolist() == [0.05, 0.075, 0.10, 0.125, 0.15]
    assert len(valid) == 5
    assert valid["n_exceed"].is_monotonic_increasing
    assert np.isfinite(valid[["xi", "evt_var_99", "evt_es_99"]].to_numpy()).all()


def test_evt_posterior_intervals_are_reproducible_and_ordered() -> None:
    rng = np.random.default_rng(101)
    returns = pd.Series(rng.standard_t(df=4, size=1_000) * 0.01)

    first = evt_posterior_intervals(returns, draws=900, burn_in=300, seed=777)
    second = evt_posterior_intervals(returns, draws=900, burn_in=300, seed=777)

    assert first["status"] == "ok"
    assert first["posterior_samples"] == 600
    assert 0.05 <= first["acceptance_rate"] <= 0.95
    for key in ["xi", "beta", "evt_var_99", "evt_es_99"]:
        assert first[key]["p05"] <= first[key]["p50"] <= first[key]["p95"]
        assert first[key] == second[key]
