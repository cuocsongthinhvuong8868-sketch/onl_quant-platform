from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tools.capitulation_regime import (
    CapitulationPhase,
    analyze_capitulation,
)


def _market_history(periods: int = 360, tickers: int = 30, seed: int = 17):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-02", periods=periods, freq="B")
    common = rng.normal(0.00045, 0.003, periods)
    idiosyncratic = rng.normal(0.0, 0.0025, (periods, tickers))
    returns = common[:, None] + idiosyncratic
    prices = 100.0 * np.exp(np.cumsum(returns, axis=0))
    columns = [f"S{i:02d}" for i in range(tickers)]
    close = pd.DataFrame(prices, index=index, columns=columns)
    index_close = close.mean(axis=1).rename("INDEX")
    base_volume = rng.lognormal(mean=np.log(1_000_000), sigma=0.08, size=(periods, tickers))
    volume = pd.DataFrame(base_volume, index=index, columns=columns)
    return index_close, close, volume


def _fragile_market():
    index_close, close, volume = _market_history()
    # A broad, orderly 12% decline creates structural fragility without a
    # one-session liquidation shock.  Turnover also dries up progressively.
    decline = np.linspace(1.0, 0.88, 45)
    close.iloc[-45:] = close.iloc[-45:].mul(decline, axis=0)
    volume.iloc[-25:] *= np.linspace(0.85, 0.58, 25)[:, None]
    volume.iloc[-4:] *= 0.55
    index_close = close.mean(axis=1).rename("INDEX")
    return index_close, close, volume


def _climax_market(with_confirmation: bool = False):
    extra = 2 if with_confirmation else 0
    index_close, close, volume = _market_history(periods=360 + extra)
    climax_position = -3 if with_confirmation else -1

    # Establish already-weak structure before the forced-selling day.
    start = climax_position - 24
    stop = climax_position
    close.iloc[start:stop] = close.iloc[start:stop].mul(
        np.linspace(1.0, 0.91, stop - start)[:, None], axis=0
    )
    close.iloc[climax_position] = close.iloc[climax_position - 1] * np.linspace(0.94, 0.955, close.shape[1])
    volume.iloc[climax_position] = volume.iloc[climax_position - 1] * 3.2

    if with_confirmation:
        close.iloc[-2] = close.iloc[-3] * np.linspace(1.015, 1.027, close.shape[1])
        close.iloc[-1] = close.iloc[-2] * np.linspace(1.012, 1.022, close.shape[1])
        volume.iloc[-2] = volume.iloc[-4] * 0.95
        volume.iloc[-1] = volume.iloc[-4] * 0.90

    index_close = close.mean(axis=1).rename("INDEX")
    return index_close, close, volume


def test_current_like_weak_market_is_fragile_not_capitulation() -> None:
    index_close, close, volume = _fragile_market()

    snapshot = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        esr_metrics={"ssi": 0.63, "state": "ACTIVE_STRESS"},
        abm_metrics={
            "vulnerability": 0.70,
            "distance_to_margin_call_pct": 7.0,
            "panic_pct": 4.9,
            "orange_pct": 20.0,
            "red_pct": 5.0,
        },
    )

    assert snapshot.phase is CapitulationPhase.FRAGILE
    assert snapshot.features["drawdown"] < -0.07
    assert snapshot.features["breadth_ma20"] < 0.30
    assert snapshot.features["turnover_ratio_20"] < 0.75
    assert snapshot.liquidation_risk_score_uncalibrated < 80
    assert "three-gate climax" not in " ".join(snapshot.trigger_reasons)


def test_price_breadth_and_forced_selling_gates_create_true_climax() -> None:
    index_close, close, volume = _climax_market()

    snapshot = analyze_capitulation(index_close, close, constituent_volume=volume)

    assert snapshot.phase is CapitulationPhase.CAPITULATION_CLIMAX
    assert snapshot.action_eligible is False
    assert snapshot.sessions_after_three_gate_climax == 0
    assert snapshot.required_gates_met == {
        "price_shock": True,
        "breadth_shock": True,
        "forced_selling": True,
        "three_gate_climax": True,
        "climax_continuation": False,
        "post_climax_exhaustion": False,
    }
    assert snapshot.features["return_1d"] < -0.035
    assert snapshot.features["downside_participation"] >= 0.80
    assert snapshot.features["selling_volume_shock"] >= 1.50
    assert snapshot.percentiles["daily_loss"] >= 0.95
    reasons = " ".join(snapshot.trigger_reasons)
    assert "price shock" in reasons
    assert "breadth shock" in reasons
    assert "turnover shock" in reasons


def test_climax_without_forced_selling_evidence_stays_liquidation() -> None:
    index_close, close, volume = _climax_market()
    volume.iloc[-1] = volume.iloc[-2]

    snapshot = analyze_capitulation(index_close, close, constituent_volume=volume)

    assert snapshot.phase is CapitulationPhase.LIQUIDATION
    assert snapshot.features["selling_volume_shock"] < 1.50


def test_partial_volume_panel_cannot_satisfy_forced_selling_gate() -> None:
    index_close, close, volume = _climax_market()
    volume.iloc[:, :25] = np.nan

    snapshot = analyze_capitulation(index_close, close, constituent_volume=volume)

    assert snapshot.features["turnover_coverage"] == 5 / 30
    assert snapshot.required_gates_met["forced_selling"] is False
    assert snapshot.phase is CapitulationPhase.LIQUIDATION
    assert snapshot.data_quality.status == "LIMITED"


def test_abm_cascade_metrics_can_supply_independent_forced_selling_gate() -> None:
    index_close, close, volume = _climax_market()
    volume.iloc[-1] = volume.iloc[-2]

    snapshot = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        abm_metrics={
            "cascade_vulnerability": 82.0,
            "distance_to_cascade_pct": 4.0,
        },
    )

    assert snapshot.phase is CapitulationPhase.CAPITULATION_CLIMAX
    assert snapshot.required_gates_met["forced_selling"] is True
    assert any("ABM metrics" in reason for reason in snapshot.trigger_reasons)


def test_dated_abm_only_climax_opens_numbered_continuation_window() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)
    climax_date = index_close.index[-3]
    volume.iloc[-3] = volume.iloc[-4]

    abm = pd.DataFrame(
        {
            "cascade_vulnerability": 0.40,
            "distance_to_cascade": 0.10,
        },
        index=index_close.index,
    )
    abm.loc[climax_date, "cascade_vulnerability"] = 0.85
    abm.loc[climax_date, "distance_to_cascade"] = 0.03

    climax = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        abm_metrics=abm,
        as_of=climax_date,
    )
    confirmed = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        abm_metrics=abm,
    )

    assert climax.phase is CapitulationPhase.CAPITULATION_CLIMAX
    assert climax.required_gates_met["forced_selling"] is True
    assert climax.features["selling_volume_shock"] < 1.50
    assert confirmed.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert confirmed.action_eligible is True
    assert confirmed.sessions_after_three_gate_climax == 2
    assert confirmed.required_gates_met["climax_continuation"] is True
    assert confirmed.features["recent_climax_sessions_ago"] == 2.0

    future_date = index_close.index[-1] + pd.offsets.BDay()
    with_future_abm = pd.concat(
        [
            abm,
            pd.DataFrame(
                {
                    "cascade_vulnerability": [0.99],
                    "distance_to_cascade": [0.01],
                },
                index=[future_date],
            ),
        ]
    )
    same_as_of = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        abm_metrics=with_future_abm,
        as_of=index_close.index[-1],
    )

    assert same_as_of.phase is confirmed.phase
    assert same_as_of.required_gates_met == confirmed.required_gates_met


def test_exhaustion_remains_diagnostic_during_actionable_continuation() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)

    snapshot = analyze_capitulation(index_close, close, constituent_volume=volume)

    assert snapshot.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert snapshot.action_eligible is True
    assert snapshot.sessions_after_three_gate_climax == 2
    assert snapshot.required_gates_met["climax_continuation"] is True
    assert snapshot.required_gates_met["post_climax_exhaustion"] is True
    assert snapshot.features["recent_climax_sessions_ago"] == 2.0
    assert snapshot.exhaustion_evidence_score_uncalibrated >= 60
    assert any("price bounced" in reason for reason in snapshot.confirmation_reasons)
    assert any("downside participation receded" in reason for reason in snapshot.confirmation_reasons)


def test_continuation_action_does_not_require_forced_selling_to_clear() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)

    snapshot = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        abm_metrics={
            "cascade_vulnerability": 0.90,
            "distance_to_cascade_pct": 2.0,
        },
    )

    assert snapshot.required_gates_met["forced_selling"] is True
    assert snapshot.required_gates_met["post_climax_exhaustion"] is False
    assert snapshot.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert snapshot.sessions_after_three_gate_climax == 2
    assert snapshot.action_eligible is True


def test_each_post_climax_session_is_numbered_from_one() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)

    first = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        as_of=index_close.index[-2],
    )
    second = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
    )

    assert first.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert first.sessions_after_three_gate_climax == 1
    assert first.action_eligible is True
    assert second.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert second.sessions_after_three_gate_climax == 2
    assert second.action_eligible is True


def test_continuation_window_ends_after_session_five() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)
    future_index = pd.date_range(
        index_close.index[-1] + pd.offsets.BDay(),
        periods=4,
        freq="B",
    )
    future_close = pd.DataFrame(
        [close.iloc[-1].to_numpy() * (1.001**step) for step in range(1, 5)],
        index=future_index,
        columns=close.columns,
    )
    future_volume = pd.DataFrame(
        np.repeat(volume.iloc[[-1]].to_numpy(), 4, axis=0),
        index=future_index,
        columns=volume.columns,
    )
    extended_close = pd.concat([close, future_close])
    extended_volume = pd.concat([volume, future_volume])
    extended_index_close = extended_close.mean(axis=1).rename("INDEX")

    fifth = analyze_capitulation(
        extended_index_close,
        extended_close,
        constituent_volume=extended_volume,
        as_of=future_index[-2],
    )
    sixth = analyze_capitulation(
        extended_index_close,
        extended_close,
        constituent_volume=extended_volume,
    )

    assert fifth.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert fifth.sessions_after_three_gate_climax == 5
    assert fifth.action_eligible is True
    assert sixth.phase is not CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert sixth.sessions_after_three_gate_climax is None
    assert sixth.action_eligible is False


def test_as_of_snapshot_is_invariant_to_appended_future_data() -> None:
    index_close, close, volume = _fragile_market()
    as_of = index_close.index[-1]
    first = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        esr_metrics={"ssi": pd.Series(0.63, index=index_close.index)},
        as_of=as_of,
    )

    future_index = pd.date_range(as_of + pd.offsets.BDay(), periods=10, freq="B")
    future_close = pd.DataFrame(
        np.linspace(0.75, 1.30, 10)[:, None] * close.iloc[-1].to_numpy(),
        index=future_index,
        columns=close.columns,
    )
    future_volume = pd.DataFrame(
        8_000_000.0,
        index=future_index,
        columns=volume.columns,
    )
    extended_close = pd.concat([close, future_close])
    extended_index_close = extended_close.mean(axis=1).rename("INDEX")
    extended_volume = pd.concat([volume, future_volume])
    extended_ssi = pd.Series(
        np.r_[np.full(len(index_close), 0.63), np.full(10, 0.99)],
        index=extended_index_close.index,
    )

    second = analyze_capitulation(
        extended_index_close,
        extended_close,
        constituent_volume=extended_volume,
        esr_metrics={"ssi": extended_ssi},
        as_of=as_of,
    )

    assert first.phase is second.phase
    assert first.features == second.features
    assert first.percentiles == second.percentiles
    assert first.stress_risk_score_uncalibrated == second.stress_risk_score_uncalibrated
    assert first.liquidation_risk_score_uncalibrated == second.liquidation_risk_score_uncalibrated


def test_insufficient_data_quality_does_not_block_continuation_action() -> None:
    index_close, close, volume = _climax_market(with_confirmation=True)
    # Keep enough prior observations to detect the climax, but fewer than the
    # 200 sessions required for a complete structural-quality assessment.
    index_close = index_close.iloc[-190:]
    close = close.iloc[-190:]
    volume = volume.iloc[-190:]

    snapshot = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
    )

    assert snapshot.data_quality.constituent_count == 30
    assert snapshot.data_quality.index_observations == 190
    assert snapshot.data_quality.status == "INSUFFICIENT"
    assert snapshot.phase is CapitulationPhase.CAPITULATION_CLIMAX_CONTINUATION
    assert snapshot.sessions_after_three_gate_climax == 2
    assert snapshot.action_eligible is True


def test_snapshot_dict_is_json_friendly_and_labels_scores_as_uncalibrated() -> None:
    index_close, close, volume = _fragile_market()
    payload = analyze_capitulation(index_close, close, constituent_volume=volume).to_dict()

    assert payload["phase"] == "FRAGILE"
    assert payload["as_of"].startswith("2025-")
    assert payload["methodology_version"].startswith("capitulation_state_machine_v")
    assert "not probabilities" in payload["score_interpretation"]
    assert payload["data_quality"]["percentile_method"].startswith("prior-only")
    json.dumps(payload)


def test_ai_cio_external_metric_aliases_are_normalized() -> None:
    index_close, close, volume = _fragile_market()
    snapshot = analyze_capitulation(
        index_close,
        close,
        constituent_volume=volume,
        esr_metrics={"ssi_pct": 63.0},
        abm_metrics={
            "cascade_vulnerability": 70.0,
            "distance_to_cascade_pct": 7.0,
            "panic_ratio_pct": 4.9,
        },
    )

    assert snapshot.features["esr_ssi"] == 0.63
    assert snapshot.features["abm_vulnerability"] == 0.70
    assert snapshot.features["abm_margin_distance"] == 0.07
    assert snapshot.features["abm_panic_share"] == 0.049
