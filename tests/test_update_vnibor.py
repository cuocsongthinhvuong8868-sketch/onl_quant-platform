from __future__ import annotations

import datetime

from command.update_vnibor import _timestamp_ms_to_vietnam_date


def test_wichart_timestamp_uses_vietnam_calendar_date() -> None:
    timestamp_ms = int(
        datetime.datetime(
            2026,
            7,
            21,
            17,
            0,
            tzinfo=datetime.timezone.utc,
        ).timestamp()
        * 1000
    )

    assert _timestamp_ms_to_vietnam_date(timestamp_ms) == "2026-07-22"


def test_wichart_historical_timestamp_does_not_shift_to_previous_utc_date() -> None:
    assert _timestamp_ms_to_vietnam_date(1722186000000) == "2024-07-29"
