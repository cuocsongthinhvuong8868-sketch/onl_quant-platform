"""
Auto-run AI CIO Executive Summary with DeepSeek, create PDF, and send to Telegram.
Designed for GitHub Actions cron job (3:00 AM VN, Mon-Fri).

Environment variables (from GitHub Secrets):
- DEEPSEEK_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Logic (default mode — dùng cho cron):
LUÔN chạy ở chế độ FORCE: xoá cache cũ của 9 tool con + executive_summary
- Gọi API mới cho toàn bộ 9 tool con + tổng hợp (10 lần gọi API)
- Tạo PDF → Gửi Telegram

Lưu ý: Workflow bên ngoài (ai_cio_daily.yml) đã kiểm tra data VNINDEX trước khi gọi script này.
Nếu thiếu data VNINDEX hôm nay → workflow tự chạy update_data.py trước.

Usage:
    python command/run_ai_cio_auto.py           # force mode (xoá cache cũ, gọi API mới)
    python command/run_ai_cio_auto.py --force   # giống default (luôn force)
"""
import os
import sys
from datetime import date
from pathlib import Path

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_LAKE
from shared.ai_cio import (
    run_executive_summary, _clear_all_tool_caches,
    parse_score_regime, summarize_executive_report_for_telegram,   # re-export từ shared
)
from shared.pdf_export import create_ai_cio_pdf

# ── Config ──
PROVIDER_KEY = "deepseek-v4-pro"
TODAY_STR = date.today().strftime('%d%m%y')
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

PDF_PATH = REPORTS_DIR / f"{TODAY_STR}_{PROVIDER_KEY.replace('-', '_')}_executive_summary.pdf"

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_SEND_FULL_PDF = os.getenv("TELEGRAM_SEND_FULL_PDF", "0").strip().lower() in {"1", "true", "yes", "on"}

FORCE = True  # luôn force — không dùng cache, gọi API mới mỗi lần


# ── Helpers ──
def _get_report_text() -> str:
    """Luôn xoá cache cũ và tạo báo cáo mới từ đầu (force mode)."""
    print(f"[FORCE] Clearing all tool caches for {PROVIDER_KEY}...")
    _clear_all_tool_caches(PROVIDER_KEY)
    print("[FORCE] All tool caches deleted. Will regenerate from scratch.")

    if not DEEPSEEK_KEY:
        print("[ERROR] DEEPSEEK_API_KEY not set.")
        sys.exit(1)

    print("[RUN] Generating AI CIO Executive Summary via DeepSeek (FORCE, source=auto)...")
    try:
        # source="auto": ghi vào CSV với marker để phân biệt với user manual run.
        # Nếu user chạy manual sau đó cùng ngày → manual sẽ ghi đè (semantic: user trust > cron).
        report_text = run_executive_summary(
            DEEPSEEK_KEY, provider_key=PROVIDER_KEY, force=True, source="auto",
        )
    except Exception as e:
        print(f"[ERROR] Failed to generate report: {e}")
        sys.exit(1)

    if not report_text:
        print("[ERROR] Report is empty.")
        sys.exit(1)

    return report_text


# NOTE: _parse_score_regime + _append_to_csv đã move sang shared/ai_cio.py
# (parse_score_regime + upsert_history_csv).
# run_executive_summary() trong shared/ai_cio.py giờ TỰ ĐỘNG upsert CSV — auto
# script không cần gọi nữa, chỉ pass source="auto" là đủ.


def _send_telegram(score_val: str, regime_val: str, summary_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram.")
        return

    import requests
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
        print("[TG] Full PDF sending disabled. Set TELEGRAM_SEND_FULL_PDF=1 to attach it.")
        return

    print("[TG] Sending PDF...")
    try:
        with open(PDF_PATH, "rb") as f:
            r = requests.post(
                f"{bot_api}/sendDocument",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"Báo cáo AI CIO — {date.today().strftime('%d/%m/%Y')}"},
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
    report_text = _get_report_text()

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

    # 4. Tạo Telegram summary ngắn bằng DeepSeek V4 Pro
    print("[SUMMARY] Creating Telegram brief via DeepSeek V4 Pro...")
    try:
        summary_text = summarize_executive_report_for_telegram(
            DEEPSEEK_KEY,
            report_text,
            provider_key=PROVIDER_KEY,
            force=True,
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
