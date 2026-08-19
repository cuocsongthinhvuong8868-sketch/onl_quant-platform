from __future__ import annotations

import pytest

from command import run_ai_cio_auto as auto


class _BalanceResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.ok = 200 <= status_code < 300

    def json(self) -> dict:
        return self._payload


class _ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_BalanceResponse(200, {"is_available": True}), "available"),
        (_BalanceResponse(200, {"is_available": False}), "insufficient_balance"),
        (_BalanceResponse(402), "insufficient_balance"),
        (_BalanceResponse(401), "authentication_error"),
        (_BalanceResponse(503), "unknown"),
    ],
)
def test_deepseek_balance_preflight_maps_account_status(
    monkeypatch, response, expected
):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "test-key")
    monkeypatch.setattr(auto.requests, "get", lambda *args, **kwargs: response)

    assert auto._get_deepseek_account_status() == expected


def test_insufficient_balance_reuses_valid_report_without_generation(
    monkeypatch, capsys
):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "test-key")
    monkeypatch.setattr(auto, "_read_cache", lambda *args: "cached report")
    monkeypatch.setattr(
        auto,
        "_get_deepseek_account_status",
        lambda: "insufficient_balance",
    )

    def unexpected_generation(*args, **kwargs):
        raise AssertionError("force generation must not run with an exhausted balance")

    monkeypatch.setattr(auto, "run_executive_summary", unexpected_generation)

    report, used_cache = auto._get_report_text()

    assert report == "cached report"
    assert used_cache is True
    assert "no AI cache was deleted" in capsys.readouterr().out


def test_insufficient_balance_without_valid_report_fails_before_generation(monkeypatch):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "test-key")
    monkeypatch.setattr(auto, "_read_cache", lambda *args: None)
    monkeypatch.setattr(
        auto,
        "_get_deepseek_account_status",
        lambda: "insufficient_balance",
    )

    def unexpected_generation(*args, **kwargs):
        raise AssertionError("force generation must not run with an exhausted balance")

    monkeypatch.setattr(auto, "run_executive_summary", unexpected_generation)

    with pytest.raises(SystemExit) as exc_info:
        auto._get_report_text()

    assert exc_info.value.code == 1


def test_available_balance_runs_one_fingerprint_aware_generation(monkeypatch):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "test-key")
    monkeypatch.setattr(auto, "_read_cache", lambda *args: "old report")
    monkeypatch.setattr(auto, "_get_deepseek_account_status", lambda: "available")
    calls = []

    def generate(api_key, *, provider_key, force, source):
        calls.append((api_key, provider_key, force, source))
        return "fresh report"

    monkeypatch.setattr(auto, "run_executive_summary", generate)

    report, used_cache = auto._get_report_text()

    assert report == "fresh report"
    assert used_cache is False
    assert calls == [("test-key", auto.PROVIDER_KEY, False, "auto")]


def test_force_generation_402_restores_state_then_reuses_report(monkeypatch):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "test-key")
    monkeypatch.setattr(auto, "_read_cache", lambda *args: "cached report")
    monkeypatch.setattr(auto, "_get_deepseek_account_status", lambda: "available")
    monkeypatch.setattr(auto, "_snapshot_generation_state", lambda: {"state": b"old"})
    restored = []
    monkeypatch.setattr(auto, "_restore_generation_state", restored.append)

    def fail_generation(*args, **kwargs):
        raise _ApiError(402, "Insufficient Balance")

    monkeypatch.setattr(auto, "run_executive_summary", fail_generation)

    report, used_cache = auto._get_report_text()

    assert report == "cached report"
    assert used_cache is True
    assert restored == [{"state": b"old"}]


def test_generation_state_rollback_restores_old_files_and_removes_partial_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(auto, "DATA_LAKE", tmp_path)
    monkeypatch.setattr(auto, "TODAY_STR", "250726")
    cache_dir = tmp_path / "daily_cache"
    metrics_dir = tmp_path / "ai_cio_metrics"
    cache_dir.mkdir()
    metrics_dir.mkdir()

    old_report = (
        cache_dir / f"executive_summary_{auto.PROVIDER_KEY}_{auto.TODAY_STR}.txt"
    )
    latest_metrics = metrics_dir / f"latest_{auto.PROVIDER_KEY}.json"
    old_report.write_bytes(b"old report")
    latest_metrics.write_bytes(b"old metrics")
    snapshot = auto._snapshot_generation_state()

    old_report.unlink()
    latest_metrics.write_bytes(b"partial metrics")
    partial_cache = cache_dir / f"feargreed_{auto.PROVIDER_KEY}_{auto.TODAY_STR}.txt"
    partial_cache.write_bytes(b"partial cache")

    auto._restore_generation_state(snapshot)

    assert old_report.read_bytes() == b"old report"
    assert latest_metrics.read_bytes() == b"old metrics"
    assert not partial_cache.exists()


def test_authentication_error_fails_before_force_generation(monkeypatch):
    monkeypatch.setattr(auto, "DEEPSEEK_KEY", "bad-key")
    monkeypatch.setattr(auto, "_read_cache", lambda *args: "cached report")
    monkeypatch.setattr(
        auto,
        "_get_deepseek_account_status",
        lambda: "authentication_error",
    )

    def unexpected_generation(*args, **kwargs):
        raise AssertionError(
            "force generation must not run after authentication failure"
        )

    monkeypatch.setattr(auto, "run_executive_summary", unexpected_generation)

    with pytest.raises(SystemExit) as exc_info:
        auto._get_report_text()

    assert exc_info.value.code == 1
