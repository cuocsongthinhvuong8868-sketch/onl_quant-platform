"""
Auto-run AI CIO Executive Summary with DeepSeek, create PDF, and send to Telegram.
Designed for the GitHub Actions weekday schedule (18:45 Asia/Bangkok).

Environment variables (from GitHub Secrets):
- DEEPSEEK_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Logic (default mode — dùng cho cron):
- Kiểm tra key/số dư DeepSeek trước khi chạy pipeline.
- Nếu API khả dụng: tính structured context và tái sử dụng executive summary theo content fingerprint khi input không đổi.
- Nếu hết số dư nhưng đã có report hợp lệ hôm nay: giữ cache và dùng report đó.
- Nếu API lỗi giữa chừng: rollback cache/metrics; chỉ fallback khi lỗi là HTTP 402.
- Tạo PDF → Gửi Telegram.

Lưu ý: Workflow bên ngoài (ai_cio_daily.yml) đã kiểm tra data VNINDEX trước khi gọi script này.
Nếu thiếu data VNINDEX hôm nay → workflow tự chạy update_data.py trước.

Usage:
    python command/run_ai_cio_auto.py           # fingerprint-aware; chỉ gọi model khi input đổi
"""

import os
import sys
from datetime import date
from pathlib import Path
from typing import Literal

import requests

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_LAKE  # noqa: E402
from shared.ai_cio import (  # noqa: E402
    run_executive_summary,
    _read_cache,
    parse_score_regime,
    summarize_executive_report_for_telegram,  # re-export từ shared
)
from shared.pdf_export import create_ai_cio_pdf  # noqa: E402

# ── Config ──
PROVIDER_KEY = "deepseek-v4-pro"
TODAY_STR = date.today().strftime("%d%m%y")
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

PDF_PATH = (
    REPORTS_DIR / f"{TODAY_STR}_{PROVIDER_KEY.replace('-', '_')}_executive_summary.pdf"
)

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_SEND_FULL_PDF = os.getenv("TELEGRAM_SEND_FULL_PDF", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


# ── Helpers ──
DeepSeekAccountStatus = Literal[
    "available", "insufficient_balance", "authentication_error", "unknown"
]
GenerationState = dict[Path, bytes | None]


def _today_provider_cache_paths() -> set[Path]:
    cache_dir = DATA_LAKE / "daily_cache"
    if not cache_dir.exists():
        return set()
    suffix = f"_{PROVIDER_KEY}_{TODAY_STR}"
    return {
        path
        for path in cache_dir.iterdir()
        if path.is_file() and path.stem.endswith(suffix)
    }


def _generation_state_paths() -> set[Path]:
    metrics_dir = DATA_LAKE / "ai_cio_metrics"
    return _today_provider_cache_paths() | {
        metrics_dir / f"metrics_{PROVIDER_KEY}_{TODAY_STR}.json",
        metrics_dir / f"metrics_{TODAY_STR}.json",
        metrics_dir / f"latest_{PROVIDER_KEY}.json",
        metrics_dir / "latest.json",
    }


def _snapshot_generation_state() -> GenerationState:
    """Capture files that force generation can delete or overwrite."""
    return {
        path: path.read_bytes() if path.exists() else None
        for path in _generation_state_paths()
    }


def _restore_generation_state(snapshot: GenerationState) -> None:
    """Roll back partial force-generation output after an API failure."""
    paths = set(snapshot) | _generation_state_paths()
    for path in paths:
        content = snapshot.get(path)
        if content is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _is_insufficient_balance_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 402:
        return True
    message = str(exc).lower()
    return "402" in message and "insufficient balance" in message


def _get_deepseek_account_status() -> DeepSeekAccountStatus:
    """Check account availability before force mode deletes today's valid caches."""
    try:
        response = requests.get(
            DEEPSEEK_BALANCE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        print(
            f"[WARN] DeepSeek balance preflight unavailable ({exc}). Will try report generation."
        )
        return "unknown"

    if response.status_code in {401, 403}:
        return "authentication_error"
    if response.status_code == 402:
        return "insufficient_balance"
    if not response.ok:
        print(
            f"[WARN] DeepSeek balance preflight returned HTTP {response.status_code}. "
            "Will try report generation."
        )
        return "unknown"

    try:
        payload = response.json()
    except ValueError:
        print(
            "[WARN] DeepSeek balance preflight returned invalid JSON. Will try report generation."
        )
        return "unknown"

    is_available = payload.get("is_available")
    if is_available is True:
        return "available"
    if is_available is False:
        return "insufficient_balance"

    print(
        "[WARN] DeepSeek balance preflight omitted is_available. Will try report generation."
    )
    return "unknown"


def _get_report_text() -> tuple[str, bool]:
    """Return today's report and whether a valid existing cache was used."""

    if not DEEPSEEK_KEY:
        print("[ERROR] DEEPSEEK_API_KEY not set.")
        sys.exit(1)

    # Read before force mode clears caches. _read_cache also rejects stale versions.
    cached_report = _read_cache("executive_summary", PROVIDER_KEY)
    account_status = _get_deepseek_account_status()
    if account_status == "authentication_error":
        print(
            "[ERROR] DeepSeek rejected DEEPSEEK_API_KEY during balance preflight (HTTP 401/403)."
        )
        sys.exit(1)
    if account_status == "insufficient_balance":
        if cached_report:
            print(
                "::warning title=DeepSeek balance exhausted::"
                "Using the existing valid AI CIO report for today; no AI cache was deleted."
            )
            return cached_report, True
        print(
            "::error title=DeepSeek balance exhausted::"
            "DEEPSEEK_API_KEY has insufficient balance and no valid AI CIO report exists for today. "
            "Top up the DeepSeek account, then rerun this workflow."
        )
        sys.exit(1)

    print("[RUN] Building AI CIO Executive Summary (fingerprint cache, source=auto)...")
    generation_snapshot = _snapshot_generation_state()
    try:
        # source="auto": ghi vào CSV với marker để phân biệt với user manual run.
        # Nếu user chạy manual sau đó cùng ngày → manual sẽ ghi đè (semantic: user trust > cron).
        report_text = run_executive_summary(
            DEEPSEEK_KEY,
            provider_key=PROVIDER_KEY,
            force=False,
            source="auto",
        )
    except Exception as e:
        try:
            _restore_generation_state(generation_snapshot)
        except OSError as restore_error:
            print(
                f"[ERROR] Failed to restore AI CIO cache after API failure: {restore_error}"
            )
            print(f"[ERROR] Original report generation failure: {e}")
            sys.exit(1)
        if _is_insufficient_balance_error(e) and cached_report:
            print(
                "::warning title=DeepSeek balance exhausted during generation::"
                "Restored AI CIO cache state and reused today's existing valid report."
            )
            return cached_report, True
        print(f"[ERROR] Failed to generate report: {e}")
        sys.exit(1)

    if not report_text:
        _restore_generation_state(generation_snapshot)
        print("[ERROR] Report is empty.")
        sys.exit(1)

    return report_text, False


# NOTE: _parse_score_regime + _append_to_csv đã move sang shared/ai_cio.py
# (parse_score_regime + upsert_history_csv).
# run_executive_summary() trong shared/ai_cio.py giờ TỰ ĐỘNG upsert CSV — auto
# script không cần gọi nữa, chỉ pass source="auto" là đủ.


def _send_telegram(score_val: str, regime_val: str, summary_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "[WARN] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram."
        )
        return

    bot_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    msg_text = summary_text.strip() or (
        f"AI CIO Daily Brief\n"
        f"Date: {date.today().strftime('%d/%m/%Y')}\n"
        f"Model: DeepSeek V4 Pro\n"
        f"Score/Regime: {score_val}/100 - {regime_val}"
    )

    print("[TG] Sending summary text message...")
    try:
        r = requests.post(
            f"{bot_api}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg_text},
            timeout=30,
        )
        r.raise_for_status()
        print("[TG] Summary text sent.")
    except Exception as e:
        print(f"[ERROR] Telegram text failed: {e}")

    if not TELEGRAM_SEND_FULL_PDF:
        print(
            "[TG] Full PDF sending disabled. Set TELEGRAM_SEND_FULL_PDF=1 to attach it."
        )
        return

    print("[TG] Sending PDF...")
    try:
        with open(PDF_PATH, "rb") as f:
            r = requests.post(
                f"{bot_api}/sendDocument",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": f"Báo cáo AI CIO — {date.today().strftime('%d/%m/%Y')}",
                },
                files={"document": (PDF_PATH.name, f, "application/pdf")},
                timeout=60,
            )
            r.raise_for_status()
        print("[TG] PDF sent.")
    except Exception as e:
        print(f"[ERROR] Telegram PDF failed: {e}")


# ── Main ──
if __name__ == "__main__":
    # 1. Lấy nội dung báo cáo
    report_text, used_cached_report = _get_report_text()

    # 2. Tạo PDF
    print("[PDF] Creating PDF...")
    try:
        create_ai_cio_pdf(
            report_text,
            PDF_PATH,
            report_date=TODAY_STR,
            provider_key=PROVIDER_KEY,
        )
        print(f"[PDF] Saved: {PDF_PATH}")
    except ImportError:
        print("[ERROR] fpdf2 not installed. Please install: pip install fpdf2>=2.7.0")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] PDF creation failed: {e}")
        sys.exit(1)

    # 3. Parse score & regime (chỉ để show ở Telegram message — CSV đã upsert tự động)
    score_val, regime_val = parse_score_regime(report_text)
    print(f"[PARSE] Score: {score_val} | Regime: {regime_val}")

    # 4. Render Telegram summary deterministically from the final report/context.
    print("[SUMMARY] Rendering deterministic Telegram brief...")
    try:
        summary_text = summarize_executive_report_for_telegram(
            DEEPSEEK_KEY,
            report_text,
            provider_key=PROVIDER_KEY,
            # Reuse today's Telegram cache after a balance fallback. If the cache
            # is absent, the exception handler below builds a deterministic brief.
            force=not used_cached_report,
        )
        print("[SUMMARY] Telegram brief ready.")
    except Exception as e:
        print(f"[WARN] Telegram summary failed, using fallback message: {e}")
        summary_text = (
            f"AI CIO Daily Brief\n"
            f"Date: {date.today().strftime('%d/%m/%Y')}\n"
            f"Model: DeepSeek V4 Pro\n"
            f"Score/Regime: {score_val}/100 - {regime_val}"
        )

    # 5. CSV history: KHÔNG cần gọi nữa — run_executive_summary() ở step 1 đã tự
    #    upsert với source="auto". Tránh gọi 2 lần (idempotent nhưng redundant).

    # 6. Gửi Telegram
    _send_telegram(score_val, regime_val, summary_text)

    print("[DONE]")
