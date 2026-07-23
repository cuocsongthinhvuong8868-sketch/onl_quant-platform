from __future__ import annotations

import numpy as np
import pandas as pd

from tools.fear_greed import report
from tools.fear_greed.quant.scoring import METHOD_VERSION


def test_fear_greed_report_snapshot_includes_v2_fields(monkeypatch) -> None:
    index = pd.date_range("2026-01-01", periods=20, freq="B")
    metrics = pd.DataFrame(
        {
            "Market_Factor": np.linspace(-0.01, 0.01, len(index)),
            "EGARCH_Vol": np.linspace(0.1, 1.0, len(index)),
            "Skewness": np.full(len(index), 1.0),
            "Downside_Corr": np.linspace(1.0, 0.1, len(index)),
            "Upside_Corr": np.linspace(0.1, 1.0, len(index)),
            "CSV_Index": np.linspace(1.0, 0.1, len(index)),
        },
        index=index,
    )
    monkeypatch.setattr(report, "calculate_quant_metrics", lambda *_args, **_kwargs: metrics)
    monkeypatch.setattr(report, "RANK_WINDOW", 10)

    row = report.snapshot(pd.DataFrame(index=index), None)

    assert row["snapshot_date"] == "2026-01-28"
    assert row["methodology_version"] == METHOD_VERSION
    assert row["sentiment_regime"] in {"GREED", "EXTREME GREED"}
    assert row["risk_score"] > 60
    assert row["fomo_push"] > row["panic_pull"]
    assert row["csv_norm"] is not None
    assert row["signal_confidence"] is not None
    assert row["dispersion_stress"] == row["csv_norm"]
    assert row["acute_shock"] is not None
    assert row["positive_impulse"] is not None
    assert row["shock_score_cap"] is not None
    assert row["shock_regime_flag"] is not None
