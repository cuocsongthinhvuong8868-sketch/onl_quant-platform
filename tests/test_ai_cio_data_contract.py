from shared import ai_cio
import numpy as np
import pandas as pd


def test_cqs_3y_percentile_parser_uses_value_not_horizon():
    packet = ai_cio._build_evidence_packet(
        "global_financial_conditions",
        "- CQS Percentile 3Y: 99.3",
        "macro",
        "17/07/2026",
    )

    assert packet["key_metrics"]["cqs_percentile"] == 99.3
    assert packet["adapter_score"]["tool_score"] == 20


def test_direct_cqs_parser_remains_supported():
    packet = ai_cio._build_evidence_packet(
        "global_financial_conditions",
        "Global FCI CQS: 84.0",
        "macro",
    )

    assert packet["key_metrics"]["cqs_percentile"] == 84.0


def test_humility_thresholds_remain_evidence_only():
    report = """
    Thesis status: WATCH
    | Model | Metric | Threshold | T actual | Status |
    | Market Breadth | Breadth MA20 | > 45% | 13.4% | INTACT |
    | ESR Monitor | SSI | < 55% | 63.0% | INTACT |
    | Global Financial Conditions | CQS Percentile | < 80 | 99.3 | INTACT |
    """

    packet = ai_cio._build_evidence_packet(
        "humility_falsification",
        report,
        "audit",
    )

    assert packet["scoring_eligible"] is False
    assert packet["key_metrics"] == {}
    assert "Thesis status: WATCH" in packet["evidence_excerpt"]
    assert "adapter_score" not in packet


def test_decision_state_ignores_legacy_humility_metrics_but_keeps_consensus():
    packets = [
        {
            "tool": "global_financial_conditions",
            "layer": "macro",
            "bias": "neutral_or_mixed",
            "key_metrics": {"cqs_percentile": 72.0},
        },
        {
            # A malformed legacy packet cannot opt an audit tool back into scoring.
            "tool": "humility_falsification",
            "layer": "audit",
            "scoring_eligible": True,
            "bias": "bearish",
            "key_metrics": {
                "cqs_percentile": 99.3,
                "breadth_ma20_pct": 13.4,
                "ssi_pct": 83.0,
            },
        },
    ]

    state = ai_cio._build_decision_state(packets, [], "20/07/2026", "17/07/2026")

    assert state["metric_values"] == {
        "global_financial_conditions.cqs_percentile": 72.0,
    }
    assert state["hard_constraints"] == []
    assert state["bias_counts"] == {
        "bullish": 0,
        "bearish": 0,
        "neutral_or_mixed": 1,
    }
    assert [item["tool"] for item in state["tool_scores"]] == [
        "global_financial_conditions",
    ]
    soft_bearish = state["consensus_map"]["soft_interpretive_consensus"]["bearish"]
    assert [item["tool"] for item in soft_bearish] == ["humility_falsification"]


def test_metrics_snapshot_marks_humility_as_audit_evidence_only():
    packet = {
        "tool": "humility_falsification",
        "layer": "audit",
        "bias": "bearish",
        "key_metrics": {"breadth_ma20_pct": 13.4},
    }

    tool = ai_cio._build_tool_metrics_snapshot([packet])["humility_falsification"]

    assert tool["scoring_eligible"] is False
    assert tool["key_metrics"] == {}
    assert tool["adapter_available"] is False
    assert tool["tool_score"] is None
    assert tool["data_quality"] == "audit_evidence_only"


def test_capitulation_gate_is_visible_but_never_aggregated():
    capitulation_state = {
        "as_of": "2026-07-17T00:00:00",
        "phase": "FRAGILE",
        "stress_risk_score_uncalibrated": 53.7,
        "liquidation_risk_score_uncalibrated": 44.2,
        "exhaustion_evidence_score_uncalibrated": 0.0,
        "features": {"breadth_ma20": 0.142, "drawdown": -0.073},
        "required_gates_met": {"three_gate_climax": False},
        "trigger_reasons": ["weak_breadth"],
        "confirmation_reasons": [],
        "data_quality": {"status": "GOOD"},
        "freshness_status": "CURRENT",
        "action_eligible": False,
    }
    gate_packet = ai_cio._build_capitulation_evidence_packet(capitulation_state)
    breadth_packet = {
        "tool": "market_breadth",
        "layer": "current_tool",
        "bias": "bearish",
        "key_metrics": {"breadth_ma20_pct": 14.2},
    }

    decision = ai_cio._build_decision_state(
        [breadth_packet, gate_packet],
        [],
        "20/07/2026",
        "17/07/2026",
    )
    decision = ai_cio._attach_capitulation_policy(decision, capitulation_state)
    snapshot = ai_cio._build_ai_cio_metrics_snapshot(
        "chatgpt-local",
        "20/07/2026",
        "17/07/2026",
        decision,
        [breadth_packet, gate_packet],
        [],
    )

    assert [item["tool"] for item in decision["tool_scores"]] == ["market_breadth"]
    assert decision["resolved_regime"] == decision["metric_implied_regime"]
    consensus_tools = {
        item["tool"]
        for layer in decision["consensus_map"].values()
        if isinstance(layer, dict)
        for bucket in layer.values()
        if isinstance(bucket, list)
        for item in bucket
    }
    assert "capitulation_regime" not in consensus_tools
    gate_tool = snapshot["tools"]["capitulation_regime"]
    assert gate_tool["diagnostic_gate_only"] is True
    assert gate_tool["key_metrics"]["phase"] == "FRAGILE"
    assert gate_tool["tool_score"] is None
    assert snapshot["score_anchor"]["capitulation_state"]["phase"] == "FRAGILE"


def test_capitulation_state_builder_fails_closed_when_index_data_is_missing(monkeypatch):
    dates = pd.date_range("2026-07-16", periods=2, freq="B")
    stocks = pd.DataFrame({"AAA": [10.0, 9.5]}, index=dates)

    def missing_index(_: str):
        raise FileNotFoundError("vnindex_cache.csv")

    monkeypatch.setattr(ai_cio, "load_custom", missing_index)
    state = ai_cio._build_capitulation_state(stocks, [])

    assert state["phase"] == "DATA_INSUFFICIENT"
    assert state["data_quality"]["status"] == "INSUFFICIENT"
    assert state["action_eligible"] is False


def test_stale_abm_metrics_are_excluded_from_current_forced_selling_gate():
    sessions = pd.bdate_range("2026-07-01", "2026-07-17")
    packets = [
        {
            "tool": "abm_simulator",
            "date": "10/07/2026",
            "key_metrics": {
                "cascade_vulnerability": 0.90,
                "distance_to_cascade_pct": 2.0,
                "panic_ratio_pct": 70.0,
            },
        }
    ]

    metrics, freshness = ai_cio._packet_metrics_as_of(
        packets,
        "abm_simulator",
        sessions,
        pd.Timestamp("2026-07-17"),
    )

    assert metrics == {}
    assert freshness == {
        "packet_date": "10/07/2026",
        "session_lag": 5,
        "status": "STALE",
        "used": False,
    }


def test_capitulation_builder_disables_actions_beyond_previous_business_session(
    monkeypatch,
):
    dates = pd.bdate_range("2026-07-01", "2026-07-17")
    stocks = pd.DataFrame({"AAA": range(len(dates))}, index=dates, dtype=float)
    index_frame = pd.DataFrame(
        {"VNINDEX": range(len(dates)), "VNINDEX_VOLUME": 100.0},
        index=dates,
        dtype=float,
    )

    class Snapshot:
        as_of = pd.Timestamp("2026-07-17")

        def to_dict(self):
            return {
                "as_of": self.as_of.isoformat(),
                "phase": "CAPITULATION_CLIMAX_CONTINUATION",
                "sessions_after_three_gate_climax": 1,
                "data_quality": {"status": "GOOD", "warnings": []},
                "action_eligible": True,
                "features": {},
                "required_gates_met": {},
            }

    packets = [
        {"tool": "esr_monitor", "date": "17/07/2026", "key_metrics": {}},
        {"tool": "abm_simulator", "date": "17/07/2026", "key_metrics": {}},
    ]
    monkeypatch.setattr(ai_cio, "load_custom", lambda _: index_frame)
    monkeypatch.setattr(ai_cio, "load_volumes", lambda: None)
    monkeypatch.setattr(ai_cio, "analyze_capitulation", lambda **_: Snapshot())

    prior_session = ai_cio._build_capitulation_state(
        stocks,
        packets,
        report_as_of="2026-07-20",
    )
    stale = ai_cio._build_capitulation_state(
        stocks,
        packets,
        report_as_of="2026-07-21",
    )

    assert prior_session["market_data_lag_business_days"] == 1
    assert prior_session["freshness_status"] == "CURRENT"
    assert prior_session["action_eligible"] is True
    assert stale["market_data_lag_business_days"] == 2
    assert stale["freshness_status"] == "STALE"
    assert stale["action_eligible"] is False


def test_capitulation_builder_uses_point_in_time_abm_history_for_prior_climax(
    tmp_path,
    monkeypatch,
):
    rng = np.random.default_rng(17)
    periods = 362
    tickers = 30
    dates = pd.bdate_range("2024-01-02", periods=periods)
    common = rng.normal(0.00045, 0.003, periods)
    idiosyncratic = rng.normal(0.0, 0.0025, (periods, tickers))
    returns = common[:, None] + idiosyncratic
    prices = 100.0 * np.exp(np.cumsum(returns, axis=0))
    stocks = pd.DataFrame(
        prices,
        index=dates,
        columns=[f"S{i:02d}" for i in range(tickers)],
    )
    volumes = pd.DataFrame(
        rng.lognormal(mean=np.log(1_000_000), sigma=0.08, size=(periods, tickers)),
        index=dates,
        columns=stocks.columns,
    )

    climax_position = -3
    start = climax_position - 24
    stocks.iloc[start:climax_position] = stocks.iloc[start:climax_position].mul(
        np.linspace(1.0, 0.91, climax_position - start)[:, None],
        axis=0,
    )
    stocks.iloc[climax_position] = stocks.iloc[climax_position - 1] * np.linspace(
        0.94,
        0.955,
        tickers,
    )
    stocks.iloc[-2] = stocks.iloc[-3] * np.linspace(1.015, 1.027, tickers)
    stocks.iloc[-1] = stocks.iloc[-2] * np.linspace(1.012, 1.022, tickers)
    volumes.iloc[-3] = volumes.iloc[-4]
    volumes.iloc[-2] = volumes.iloc[-4] * 0.95
    volumes.iloc[-1] = volumes.iloc[-4] * 0.90
    index_close = stocks.mean(axis=1).rename("VNINDEX")

    climax_date = dates[-3]
    as_of = dates[-1]
    state_rows = pd.DataFrame(
        {
            "as_of_date": [climax_date.date().isoformat(), as_of.date().isoformat()],
            "cascade_vulnerability": [0.85, 0.40],
        }
    )
    alert_rows = pd.DataFrame(
        {
            "as_of_date": [climax_date.date().isoformat(), as_of.date().isoformat()],
            "distance_to_cascade": [0.03, 0.10],
        }
    )
    state_path = tmp_path / "abm_behavioral_state.csv"
    alert_path = tmp_path / "abm_alert.csv"
    state_rows.to_csv(state_path, index=False)
    alert_rows.to_csv(alert_path, index=False)

    date_label = as_of.strftime("%d/%m/%Y")
    packets = [
        {"tool": "esr_monitor", "date": date_label, "key_metrics": {}},
        {
            "tool": "abm_simulator",
            "date": date_label,
            "key_metrics": {
                "cascade_vulnerability": 0.40,
                "distance_to_cascade": 0.10,
            },
        },
    ]
    monkeypatch.setattr(ai_cio, "DATA_LAKE", tmp_path)
    monkeypatch.setattr(
        ai_cio,
        "load_custom",
        lambda _: index_close.to_frame(),
    )
    monkeypatch.setattr(ai_cio, "load_volumes", lambda: volumes)

    confirmed = ai_cio._build_capitulation_state(
        stocks,
        packets,
        report_as_of=as_of,
    )

    assert confirmed["phase"] == "CAPITULATION_CLIMAX_CONTINUATION"
    assert confirmed["action_eligible"] is True
    assert confirmed["sessions_after_three_gate_climax"] == 2
    assert confirmed["features"]["recent_climax_sessions_ago"] == 2.0
    assert confirmed["features"]["selling_volume_shock"] < 1.50

    future_date = as_of + pd.offsets.BDay()
    pd.concat(
        [
            state_rows,
            pd.DataFrame(
                {
                    "as_of_date": [future_date.date().isoformat()],
                    "cascade_vulnerability": [0.99],
                }
            ),
        ],
        ignore_index=True,
    ).to_csv(state_path, index=False)
    pd.concat(
        [
            alert_rows,
            pd.DataFrame(
                {
                    "as_of_date": [future_date.date().isoformat()],
                    "distance_to_cascade": [0.01],
                }
            ),
        ],
        ignore_index=True,
    ).to_csv(alert_path, index=False)

    same_as_of = ai_cio._build_capitulation_state(
        stocks,
        packets,
        report_as_of=as_of,
    )
    loaded = ai_cio._load_abm_metric_history_as_of(as_of)

    assert loaded.index.max() == as_of
    assert future_date not in loaded.index
    assert same_as_of["phase"] == confirmed["phase"]
    assert same_as_of["required_gates_met"] == confirmed["required_gates_met"]
