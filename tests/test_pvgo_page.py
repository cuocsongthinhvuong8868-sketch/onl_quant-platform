from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.pvgo import page


def test_load_vnindex_history_uses_canonical_market_columns(tmp_path: Path) -> None:
    market_path = tmp_path / "vnindex_cache.csv"
    pd.DataFrame(
        {
            "time": ["2026-07-27", "2026-07-24", "2026-07-27"],
            "VNINDEX": [1_668.0, 1_686.11, 1_669.01],
            "VNINDEX_volume": [600, 500, 635],
        }
    ).to_csv(market_path, index=False)

    result = page.load_vnindex_history(market_path, market_path.stat().st_mtime)

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-24", "2026-07-27"]
    assert result["close"].tolist() == [1_686.11, 1_669.01]
    assert result["volume"].tolist() == [500, 635]


def test_vnindex_and_pe_use_separate_single_axis_figures() -> None:
    dates = pd.to_datetime(["2026-07-24", "2026-07-27"])
    market = pd.DataFrame({"date": dates, "close": [1_686.11, 1_669.01]})
    valuation = pd.DataFrame({"date": dates, "pe": [12.38, 12.21]})

    market_figure = page._plot_vnindex(market)
    pe_figure = page._plot_pe(valuation)

    assert [trace.name for trace in market_figure.data] == ["VN-Index"]
    assert [trace.name for trace in pe_figure.data] == ["P/E"]
    assert "yaxis2" not in market_figure.to_plotly_json()["layout"]
    assert "yaxis2" not in pe_figure.to_plotly_json()["layout"]


def test_stale_warning_identifies_only_the_valuation_feed(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(page.st, "warning", messages.append)

    page._render_freshness_status(
        {
            "status": "STALE",
            "source_date": "2026-07-24",
            "market_date": "2026-07-27",
            "session_lag": 1,
            "max_session_lag": 0,
        }
    )

    assert messages[0].startswith("P/E and P/B valuation freshness: STALE")
    assert "does not mean that the separate VN-Index price feed is stale" in messages[0]
