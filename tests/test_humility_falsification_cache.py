import json
from datetime import date


def test_humility_cache_accepts_runner_path_by_report_name(tmp_path, monkeypatch):
    from tools.humility_falsification import page

    data_lake = tmp_path / "data_lake"
    cache_dir = data_lake / "daily_cache"
    cache_dir.mkdir(parents=True)
    monkeypatch.setattr(page, "DATA_LAKE", data_lake)

    provider = "test-provider"
    local_report = cache_dir / f"executive_summary_{provider}_070726.txt"
    local_report.write_text("AI CIO report body", encoding="utf-8")

    cache_path = cache_dir / f"humility_falsification_{provider}_080726.json"
    cache_path.write_text(
        json.dumps(
            {
                "provider_key": provider,
                "t_data_date": "2026-07-08",
                "target_report_date": "2026-07-07",
                "report_path": (
                    "/home/runner/work/onl_quant-platform/onl_quant-platform/"
                    f"data_lake/daily_cache/{local_report.name}"
                ),
                "report_mtime": "report:2026-07-08T13:17:00",
                "rows": [],
                "current_metrics": {},
            }
        ),
        encoding="utf-8",
    )

    cached = page._read_humility_cache(
        cache_path,
        provider,
        date(2026, 7, 8),
        local_report,
        page._rule_source_signature(local_report),
        date(2026, 7, 7),
    )

    assert cached is not None
    assert cached["report_path"].endswith(local_report.name)


def test_humility_payload_can_return_latest_cache_without_recompute(tmp_path, monkeypatch):
    from tools.humility_falsification import page

    data_lake = tmp_path / "data_lake"
    cache_dir = data_lake / "daily_cache"
    cache_dir.mkdir(parents=True)
    monkeypatch.setattr(page, "DATA_LAKE", data_lake)

    provider = "test-provider"
    cache_path = cache_dir / f"humility_falsification_{provider}_080726.json"
    cache_path.write_text(
        json.dumps(
            {
                "provider_key": provider,
                "t_data_date": "2026-07-08",
                "target_report_date": "2026-07-07",
                "report_match": "exact",
                "report_path": f"/runner/data_lake/daily_cache/executive_summary_{provider}_070726.txt",
                "rows": [],
                "current_metrics": {},
                "status_label": "WATCH",
                "falsified": 1,
                "available": 6,
                "total": 6,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(page, "_latest_close_data_date", lambda: date(2026, 7, 10))
    monkeypatch.setattr(page, "_reports_by_provider", lambda: {provider: []})
    monkeypatch.setattr(
        page,
        "_compute_current_metrics_uncached",
        lambda: (_ for _ in ()).throw(AssertionError("should not recompute")),
    )

    payload = page.build_humility_falsification_payload(provider, allow_latest_cache=True)

    assert payload["cache_hit"] is True
    assert payload["cache_mode"] == "latest"
    assert payload["cache_stale"] is True
    assert payload["cache_path"] == str(cache_path)
