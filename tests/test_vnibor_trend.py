import numpy as np
import pandas as pd

from tools.vnibor.quant.metrics import summarize_20d_trend


def _vnibor_frame(on_values, signals, regimes, spreads=None):
    index = pd.date_range("2026-01-01", periods=len(on_values), freq="D")
    on = pd.Series(on_values, index=index, dtype=float)
    spreads = spreads if spreads is not None else [0.5] * len(on_values)
    return pd.DataFrame(
        {
            "Overnight_ON": on,
            "ON_5D_Mean": on.rolling(5, min_periods=1).mean(),
            "ON_Impulse": on.diff().fillna(0.0),
            "ON_ZScore": np.linspace(1.2, -0.7, len(on_values)),
            "ON_Percentile": np.linspace(0.9, 0.2, len(on_values)),
            "Spread_1W_ON": spreads,
            "Spread_2W_ON": [s + 0.1 for s in spreads],
            "Regime": regimes,
            "Signal": signals,
        },
        index=index,
    )


def test_vnibor_trend_labels_stress_unwinding_when_current_state_has_eased():
    on_values = [10, 9.6, 9.0, 8.5, 8.0, 7.4, 6.9, 6.4, 5.8, 5.2, 4.8, 4.4, 4.0, 3.8, 3.6, 3.4, 3.2, 3.1, 3.05, 3.0]
    signals = ["STRESS"] * 5 + ["WARNING"] * 2 + ["NEUTRAL"] * 13
    regimes = ["TIGHT"] * 9 + ["ELEVATED"] + ["NORMAL"] * 5 + ["EASY"] * 5
    spreads = [-0.2, -0.1] + [0.5] * 18

    trend = summarize_20d_trend(_vnibor_frame(on_values, signals, regimes, spreads), lookback=20)

    assert trend["stress_warning_days"] == "7"
    assert trend["trend_label"] == "stress unwinding / post-squeeze easing"


def test_vnibor_trend_keeps_stress_building_when_current_state_is_still_stressed():
    on_values = [3.0, 3.1, 3.2, 3.4, 3.6, 3.8, 4.0, 4.4, 4.8, 5.2, 5.8, 6.4, 6.9, 7.4, 8.0, 8.5, 9.0, 9.4, 9.8, 10.0]
    signals = ["NEUTRAL"] * 13 + ["WARNING"] * 2 + ["STRESS"] * 5
    regimes = ["EASY"] * 5 + ["NORMAL"] * 5 + ["ELEVATED"] * 3 + ["TIGHT"] * 7
    spreads = [0.5] * 16 + [-0.1, -0.2, -0.3, -0.4]

    trend = summarize_20d_trend(_vnibor_frame(on_values, signals, regimes, spreads), lookback=20)

    assert trend["stress_warning_days"] == "7"
    assert trend["trend_label"] == "liquidity squeeze / stress building"
