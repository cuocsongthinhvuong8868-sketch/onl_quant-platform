from __future__ import annotations

from pathlib import Path

from command import update_abm_data


def _write_abm_tables(source_dir: Path) -> None:
    source_dir.mkdir(parents=True)
    for table in update_abm_data.REQUIRED_TABLES + update_abm_data.OPTIONAL_TABLES:
        (source_dir / f"{table}.csv").write_text("as_of_date\n2026-09-04\n", encoding="utf-8")


def test_sync_abm_data_copies_ltmm_payloads(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "LTMM" / "data" / "gold"
    integration_dir = tmp_path / "LTMM" / "quant_platform_intergration" / "data_LTMM"
    source_raw = integration_dir / "sourse_raw"
    ai_cio_raw = integration_dir / "AI_CIO_raw"
    data_lake = tmp_path / "onl_quant-platform" / "data_lake"
    _write_abm_tables(source_dir)
    source_raw.mkdir(parents=True)
    ai_cio_raw.mkdir(parents=True)
    data_lake.mkdir(parents=True)
    (source_raw / "04092026.json").write_text("{}", encoding="utf-8")
    (ai_cio_raw / "ltmm_analyst_deepseek-v4-pro_040926.txt").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(update_abm_data, "DATA_LAKE", data_lake)

    ok = update_abm_data.sync_abm_data(
        source_dir=source_dir,
        strict=True,
        integration_dir=integration_dir,
    )

    assert ok is True
    assert (data_lake / "abm_alert.csv").exists()
    assert (data_lake / "data_LTMM" / "sourse_raw" / "04092026.json").exists()
    assert (data_lake / "data_LTMM" / "AI_CIO_raw" / "ltmm_analyst_deepseek-v4-pro_040926.txt").exists()


def test_sync_abm_data_strict_fails_when_payload_source_missing(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "LTMM" / "data" / "gold"
    data_lake = tmp_path / "onl_quant-platform" / "data_lake"
    _write_abm_tables(source_dir)
    data_lake.mkdir(parents=True)
    monkeypatch.setattr(update_abm_data, "DATA_LAKE", data_lake)

    ok = update_abm_data.sync_abm_data(
        source_dir=source_dir,
        strict=True,
        integration_dir=tmp_path / "missing_data_LTMM",
    )

    assert ok is False
