import numpy as np
import pandas as pd
import pytest

from shared.data_loader import load_close_prices, load_custom
from tools.manipulation.quant.engine import (
    METHOD_VERSION,
    TARGET,
    TARGET_RETURN_COL,
    compute_metrics,
    prepare_data,
)
from tools.manipulation.report import snapshot


def _close_frame(periods: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=periods, freq="B")
    base = np.linspace(100.0, 120.0, periods)
    return pd.DataFrame(
        {
            "VIC": base * 1.01,
            "VHM": base * 0.92,
            "VRE": base * 0.51,
            "VN30F1M": base * 10.0,
        },
        index=dates,
    )


def test_prepare_data_merges_vnindex_target_instead_of_futures():
    close = _close_frame()
    vnindex = pd.Series(np.linspace(1500.0, 1600.0, len(close)), index=close.index, name=TARGET)

    prepared = prepare_data(close, target_series=vnindex)

    assert TARGET in prepared.columns
    assert "VN30F1M" not in prepared.columns
    assert prepared[TARGET].iloc[-1] == vnindex.iloc[-1]


def test_prepare_data_requires_vnindex_target():
    close = _close_frame()

    with pytest.raises(ValueError, match="VNINDEX"):
        prepare_data(close)


def test_compute_metrics_uses_vnindex_return_without_forward_fill():
    close = _close_frame(periods=50)
    vnindex = pd.Series(np.linspace(1500.0, 1600.0, len(close)), index=close.index, name=TARGET)
    vnindex.iloc[20] = np.nan
    prepared = prepare_data(close, target_series=vnindex)

    _, result = compute_metrics(prepared, window=5)

    assert TARGET_RETURN_COL in result.columns
    assert "VN30F1M_Return" not in result.columns
    assert close.index[20] not in result.index
    assert close.index[21] not in result.index


def test_manipulation_report_snapshot_exposes_vnindex_v2_contract():
    snap = snapshot(load_close_prices(), load_custom)

    assert snap["methodology_version"] == METHOD_VERSION
    assert snap["target"] == TARGET
    assert snap["snapshot_date"]


def test_ai_cio_manipulation_footer_uses_local_scope(monkeypatch):
    import shared.ai_cio as ai_cio

    monkeypatch.setattr(ai_cio, "_read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_cio, "_write_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_cio, "call_ai", lambda *args, **kwargs: "ok")

    report = ai_cio.run_manipulation(None, load_close_prices(), provider_key="unit-test")

    assert "manipulation_methodology" in report
    assert "target=VNINDEX" in report
