from __future__ import annotations

import numpy as np
import pandas as pd

from command.diagnose_vnstock_candles import analyze_frame, compare_sources


def _frame(times, *, opens=None, volumes=None) -> pd.DataFrame:
    rows = len(times)
    opens = opens or [10.0] * rows
    volumes = volumes or [1_000] * rows
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": [11.0] * rows,
            "low": [9.0] * rows,
            "close": [10.5] * rows,
            "volume": volumes,
        }
    )


def test_daily_vci_row_before_requested_start_is_warning():
    frame = _frame(["2026-07-14", "2026-07-15"])

    check = analyze_frame(
        frame,
        symbol="FPT",
        source="VCI",
        interval="1D",
        start="2026-07-15",
        end="2026-07-15",
    )

    assert check.status == "WARN"
    assert check.outside_requested_range_rows == 1
    assert not check.issues


def test_intraday_null_ohlc_is_failure():
    frame = _frame(["2026-07-24 14:15", "2026-07-24 14:30"])
    frame.loc[1, ["open", "high", "low", "close"]] = np.nan
    frame.loc[1, "volume"] = 0

    check = analyze_frame(
        frame,
        symbol="FPT",
        source="VCI",
        interval="15m",
        start="2026-07-24",
        end="2026-07-24",
    )

    assert check.status == "FAIL"
    assert check.null_ohlc_rows == 1
    assert "dòng có OHLC rỗng: 1" in check.issues


def test_daily_comparison_normalizes_kbs_timestamp_and_finds_vci_extra_date():
    vci = _frame(["2026-07-14", "2026-07-15"])
    kbs = _frame(["2026-07-15 07:00:00"])

    comparison = compare_sources(
        vci,
        kbs,
        symbol="FPT",
        interval="1D",
    )

    assert comparison.common_rows == 1
    assert comparison.vci_only_rows == 1
    assert comparison.kbs_only_rows == 0
    assert all(item.mismatch_rows == 0 for item in comparison.fields.values())


def test_comparison_reports_index_price_and_volume_disagreement():
    vci = _frame(["2026-07-24"], opens=[1683.23], volumes=[589_610_571])
    kbs = _frame(
        ["2026-07-24 07:00:00"],
        opens=[1701.98],
        volumes=[500_000_000],
    )

    comparison = compare_sources(
        vci,
        kbs,
        symbol="VNINDEX",
        interval="1D",
    )

    assert comparison.fields["open"].mismatch_rows == 1
    assert comparison.fields["volume"].mismatch_rows == 1
    assert comparison.has_mismatch is True
