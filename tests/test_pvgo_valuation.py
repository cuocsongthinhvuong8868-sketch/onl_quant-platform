from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from tools.pvgo.freshness import evaluate_pvgo_freshness
from tools.pvgo.report import build_ai_cio_context
from tools.pvgo.quant.valuation_24hmoney import (
    API_URL,
    CORE_COLUMNS,
    Money24hVNIndexValuationScraper,
    SOURCE_NAME,
    TABLE_NAME,
    main,
)


def _valuation_row(
    trade_date: str,
    *,
    close: float,
    pe: float,
    pb: float,
) -> dict[str, object]:
    return {
        "date": dt.date.fromisoformat(trade_date),
        "index_code": "VNINDEX",
        "floor_code": "10",
        "close": close,
        "pe": pe,
        "pb": pb,
        "range_type": "5",
        "source_url": f"{API_URL}?floor_code=10&type=5",
        "source": SOURCE_NAME,
    }


def _write_market_dates(path: Path, dates: list[str]) -> None:
    pd.DataFrame(
        {
            "time": dates,
            "VNINDEX": [1_700.0 + index for index in range(len(dates))],
        }
    ).to_csv(path, index=False)


def _write_existing_history(path: Path, core_rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(core_rows, columns=CORE_COLUMNS)
    frame["scrape_run_id"] = "original-run"
    frame["scraped_at"] = "2026-07-17T20:30:00+07:00"
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame.to_csv(path, index=False)


def test_freshness_counts_market_sessions_across_weekend() -> None:
    market_dates = pd.to_datetime(["2026-07-16", "2026-07-17", "2026-07-20"])

    current = evaluate_pvgo_freshness(
        dt.date(2026, 7, 17),
        market_dates,
        max_session_lag=1,
    )
    stale = evaluate_pvgo_freshness(
        dt.date(2026, 7, 16),
        market_dates,
        max_session_lag=1,
    )

    assert current == {
        "status": "CURRENT",
        "source_date": "2026-07-17",
        "market_date": "2026-07-20",
        "session_lag": 1,
        "max_session_lag": 1,
    }
    assert stale == {
        "status": "STALE",
        "source_date": "2026-07-16",
        "market_date": "2026-07-20",
        "session_lag": 2,
        "max_session_lag": 1,
    }


def test_updater_skips_write_and_preserves_metadata_when_core_rows_are_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "pvgo"
    output_dir.mkdir()
    csv_path = output_dir / f"{TABLE_NAME}.csv"
    market_data_path = tmp_path / "vnindex_cache.csv"
    friday = _valuation_row("2026-07-17", close=1_787.45, pe=13.14, pb=2.04)
    _write_existing_history(csv_path, [friday])
    _write_market_dates(market_data_path, ["2026-07-17", "2026-07-20"])
    original_bytes = csv_path.read_bytes()

    scraper = Money24hVNIndexValuationScraper()
    monkeypatch.setattr(scraper, "scrape", lambda: pd.DataFrame([friday], columns=CORE_COLUMNS))

    stats = scraper.run(
        output_dir=output_dir,
        market_data_path=market_data_path,
        max_session_lag=1,
    )

    assert stats["freshness_status"] == "CURRENT"
    assert stats["session_lag"] == 1
    assert stats["tables_written"] == 0
    assert stats["data_changed"] is False
    assert stats["rows_added"] == 0
    assert stats["rows_updated"] == 0
    assert stats["rows_unchanged"] == 1
    assert csv_path.read_bytes() == original_bytes

    persisted = pd.read_csv(csv_path, dtype={"scrape_run_id": str})
    assert persisted.loc[0, "scrape_run_id"] == "original-run"
    assert persisted.loc[0, "scraped_at"] == "2026-07-17T20:30:00+07:00"


def test_updater_stamps_only_a_genuinely_new_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "pvgo"
    output_dir.mkdir()
    csv_path = output_dir / f"{TABLE_NAME}.csv"
    market_data_path = tmp_path / "vnindex_cache.csv"
    friday = _valuation_row("2026-07-17", close=1_787.45, pe=13.14, pb=2.04)
    monday = _valuation_row("2026-07-20", close=1_743.51, pe=12.83, pb=1.98)
    _write_existing_history(csv_path, [friday])
    _write_market_dates(market_data_path, ["2026-07-17", "2026-07-20"])

    scraper = Money24hVNIndexValuationScraper()
    monkeypatch.setattr(
        scraper,
        "scrape",
        lambda: pd.DataFrame([friday, monday], columns=CORE_COLUMNS),
    )

    stats = scraper.run(
        output_dir=output_dir,
        market_data_path=market_data_path,
        max_session_lag=1,
    )

    assert stats["freshness_status"] == "CURRENT"
    assert stats["session_lag"] == 0
    assert stats["tables_written"] == 1
    assert stats["data_changed"] is True
    assert stats["rows_added"] == 1
    assert stats["rows_updated"] == 0
    assert stats["rows_unchanged"] == 1

    persisted = pd.read_csv(csv_path, dtype={"scrape_run_id": str})
    assert persisted["date"].tolist() == ["2026-07-17", "2026-07-20"]
    old_row = persisted.loc[persisted["date"] == "2026-07-17"].iloc[0]
    new_row = persisted.loc[persisted["date"] == "2026-07-20"].iloc[0]
    assert old_row["scrape_run_id"] == "original-run"
    assert old_row["scraped_at"] == "2026-07-17T20:30:00+07:00"
    assert new_row["scrape_run_id"] == scraper.run_id
    assert pd.notna(new_row["scraped_at"])


def test_cli_fails_on_stale_payload_unless_explicitly_allowed(monkeypatch) -> None:
    def stale_run(self, **kwargs):
        return {"rows_ready": 10, "freshness_status": "STALE"}

    monkeypatch.setattr(Money24hVNIndexValuationScraper, "run", stale_run)

    assert main([]) == 2
    assert main(["--allow-stale"]) == 0


def test_ai_context_fails_closed_when_pvgo_exceeds_session_lag(tmp_path: Path) -> None:
    pvgo_path = tmp_path / "vnindex_valuation_history.csv"
    market_data_path = tmp_path / "vnindex_cache.csv"
    thursday = _valuation_row("2026-07-16", close=1_804.24, pe=13.34, pb=2.06)
    _write_existing_history(pvgo_path, [thursday])
    _write_market_dates(market_data_path, ["2026-07-16", "2026-07-17", "2026-07-20"])

    context = build_ai_cio_context(path=pvgo_path, market_data_path=market_data_path)

    assert context.startswith("DATA INSUFFICIENT - PVGO valuation feed STALE")
    assert "2 market sessions behind" in context


def test_ai_context_fails_closed_when_pvgo_is_one_session_behind_by_default(tmp_path: Path) -> None:
    pvgo_path = tmp_path / "vnindex_valuation_history.csv"
    market_data_path = tmp_path / "vnindex_cache.csv"
    friday = _valuation_row("2026-07-17", close=1_787.45, pe=13.14, pb=2.04)
    _write_existing_history(pvgo_path, [friday])
    _write_market_dates(market_data_path, ["2026-07-17", "2026-07-20"])

    context = build_ai_cio_context(path=pvgo_path, market_data_path=market_data_path)

    assert context.startswith("DATA INSUFFICIENT - PVGO valuation feed STALE")
    assert "1 market sessions behind" in context
    assert "(limit 0)" in context
