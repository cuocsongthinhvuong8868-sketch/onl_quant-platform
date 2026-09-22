"""Build and publish the daily AI CIO report from deterministic Python metrics.

The scheduled run does not use an AI provider key or call a language model.
Interactive AI features in the app continue to use the user's selected provider.
"""

import os
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.ai_cio import (  # noqa: E402
    AI_CIO_DETERMINISTIC_PROVIDER,
    parse_score_regime,
    run_executive_summary,
    summarize_executive_report_for_telegram,
)
from shared.pdf_export import create_ai_cio_pdf  # noqa: E402

PROVIDER_KEY = AI_CIO_DETERMINISTIC_PROVIDER
TODAY_STR = date.today().strftime("%d%m%y")
REPORTS_DIR = ROOT / "reports"
PDF_PATH = REPORTS_DIR / f"{TODAY_STR}_{PROVIDER_KEY.replace('-', '_')}_executive_summary.pdf"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_SEND_FULL_PDF = os.getenv("TELEGRAM_SEND_FULL_PDF", "0").strip().lower() in {
    "1", "true", "yes", "on",
}


def _get_report_text() -> str:
    """Recalculate the daily evidence and render the report without an API key."""
    return run_executive_summary(
        "",
        provider_key=PROVIDER_KEY,
        force=False,
        source="auto",
        report_mode="deterministic",
    )


def _send_telegram(score_val: str, regime_val: str, summary_text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram.")
        return

    bot_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    msg_text = summary_text.strip() or (
        f"AI CIO Daily Brief\n"
        f"Date: {date.today().strftime('%d/%m/%Y')}\n"
        f"Method: Python quantitative rules\n"
        f"Score/Regime: {score_val}/100 - {regime_val}"
    )

    print("[TG] Sending summary text message...")
    try:
        response = requests.post(
            f"{bot_api}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg_text},
            timeout=30,
        )
        response.raise_for_status()
        print("[TG] Summary text sent.")
    except requests.RequestException as exc:
        print(f"[ERROR] Telegram text failed: {exc}")

    if not TELEGRAM_SEND_FULL_PDF:
        print("[TG] Full PDF sending disabled. Set TELEGRAM_SEND_FULL_PDF=1 to attach it.")
        return

    print("[TG] Sending PDF...")
    try:
        with PDF_PATH.open("rb") as report_file:
            response = requests.post(
                f"{bot_api}/sendDocument",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": f"AI CIO quantitative report - {date.today().strftime('%d/%m/%Y')}",
                },
                files={"document": (PDF_PATH.name, report_file, "application/pdf")},
                timeout=60,
            )
            response.raise_for_status()
        print("[TG] PDF sent.")
    except (OSError, requests.RequestException) as exc:
        print(f"[ERROR] Telegram PDF failed: {exc}")


def main() -> None:
    report_text = _get_report_text()
    if not report_text:
        raise RuntimeError("Deterministic AI CIO report is empty")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("[PDF] Creating PDF...")
    create_ai_cio_pdf(
        report_text,
        PDF_PATH,
        report_date=TODAY_STR,
        provider_key=PROVIDER_KEY,
    )
    print(f"[PDF] Saved: {PDF_PATH}")

    score_val, regime_val = parse_score_regime(report_text)
    if score_val == "N/A" or regime_val == "N/A":
        raise RuntimeError("Deterministic AI CIO score or regime is missing")
    print(f"[PARSE] Score: {score_val} | Regime: {regime_val}")

    summary_text = summarize_executive_report_for_telegram(
        "",
        report_text,
        provider_key=PROVIDER_KEY,
        force=True,
    )
    _send_telegram(score_val, regime_val, summary_text)
    print("[DONE]")


if __name__ == "__main__":
    main()
