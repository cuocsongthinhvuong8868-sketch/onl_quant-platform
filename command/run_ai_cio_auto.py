"""
Auto-run AI CIO Executive Summary with DeepSeek, create PDF, and send to Telegram.
Designed for GitHub Actions cron job (3:00 AM VN, Mon-Fri).

Environment variables (from GitHub Secrets):
- DEEPSEEK_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Logic:
1. Check if today's cache already exists → skip if yes (use --force to override).
2. Run run_executive_summary() with DeepSeek.
3. Create PDF from report text.
4. Parse final line for score & regime.
5. Send Telegram message + PDF document.

Usage:
    python command/run_ai_cio_auto.py           # normal (skip if cache exists)
    python command/run_ai_cio_auto.py --force   # force re-run API even if cache exists
    python command/run_ai_cio_auto.py --resend  # read existing cache, create PDF, send Telegram
"""
import os
import re
import sys
from datetime import date
from pathlib import Path

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_LAKE, ROOT_DIR
from shared.ai_cio import run_executive_summary, _read_cache

# ── Config ──
PROVIDER_KEY = "deepseek-v4-pro"
TODAY_STR = date.today().strftime('%d%m%y')
CACHE_PATH = DATA_LAKE / "daily_cache" / f"executive_summary_{PROVIDER_KEY}_{TODAY_STR}.txt"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

PDF_PATH = REPORTS_DIR / f"{TODAY_STR}_{PROVIDER_KEY.replace('-', '_')}_executive_summary.pdf"

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

FORCE = "--force" in sys.argv or "-f" in sys.argv
RESEND = "--resend" in sys.argv or "-r" in sys.argv


# ── Helpers ──
def _get_report_text() -> str:
    """Lấy nội dung báo cáo: từ cache hoặc gọi API mới."""
    if RESEND and CACHE_PATH.exists():
        print(f"[RESEND] Reading existing cache: {CACHE_PATH.name}")
        cached = _read_cache("executive_summary", PROVIDER_KEY)
        if cached:
            return cached
        print("[WARN] Cache file exists but empty/corrupt. Will try API.")

    if CACHE_PATH.exists() and not FORCE and not RESEND:
        print(f"[SKIP] Cache already exists: {CACHE_PATH.name}")
        print(f"[HINT] Use --force to override and re-run API.")
        print(f"[HINT] Use --resend to read cache and send Telegram only.")
        sys.exit(0)

    if FORCE and CACHE_PATH.exists():
        print(f"[FORCE] Removing existing cache: {CACHE_PATH.name}")
        os.remove(CACHE_PATH)

    if not DEEPSEEK_KEY:
        print("[ERROR] DEEPSEEK_API_KEY not set.")
        sys.exit(1)

    print("[RUN] Generating AI CIO Executive Summary via DeepSeek...")
    try:
        report_text = run_executive_summary(DEEPSEEK_KEY, provider_key=PROVIDER_KEY)
    except Exception as e:
        print(f"[ERROR] Failed to generate report: {e}")
        sys.exit(1)

    if not report_text:
        print("[ERROR] Report is empty.")
        sys.exit(1)

    return report_text


def _create_pdf(text: str, path: str):
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    font_dir = ROOT_DIR / "fonts"
    pdf.add_font("DejaVu", "", str(font_dir / "DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu", "B", str(font_dir / "DejaVuSans-Bold.ttf"), uni=True)

    text_width = int(pdf.w - 20)

    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(10, 10)
    pdf.cell(text_width, 10, f"Executive Summary Report — {date.today().strftime('%d/%m/%Y')}", border=0, ln=1, align="C")
    pdf.ln(5)

    pdf.set_font("DejaVu", "", 11)
    for raw_line in text.split('\n'):
        line = raw_line.strip().replace('\t', ' ')
        line = re.sub(r'  +', ' ', line)
        if not line:
            pdf.ln(2)
            continue

        pdf.set_x(10)

        if line.startswith('#'):
            pdf.set_font("DejaVu", "B", 12)
            pdf.multi_cell(text_width, 7, line.lstrip('#').strip())
            pdf.set_font("DejaVu", "", 11)
        elif line.startswith('**') and line.endswith('**'):
            pdf.set_font("DejaVu", "B", 11)
            pdf.multi_cell(text_width, 6, line.replace('**', ''))
            pdf.set_font("DejaVu", "", 11)
        else:
            pdf.multi_cell(text_width, 6, line.replace('**', ''))
    pdf.output(path)


def _parse_score_regime(report_text: str) -> tuple:
    final_line = report_text.strip().splitlines()[-1]
    score_val = "N/A"
    regime_val = "N/A"

    match = re.search(
        r'final score & regime\s*[:=]\s*(\d+(?:\.\d+)?)\s*;\s*regime\s*[:=]\s*(.+)',
        final_line,
        re.IGNORECASE,
    )
    if match:
        score_val = match.group(1)
        regime_val = match.group(2).strip()
    else:
        for line in report_text.strip().splitlines()[-5:]:
            m = re.search(r'final score.*?[:=]\s*(\d+(?:\.\d+)?)', line, re.IGNORECASE)
            if m:
                score_val = m.group(1)
            m2 = re.search(r'regime\s*[:=]\s*(.+)', line, re.IGNORECASE)
            if m2:
                regime_val = m2.group(1).strip()

    return score_val, regime_val


def _send_telegram(score_val: str, regime_val: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram.")
        return

    import requests
    bot_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    msg_text = (
        f"📊 <b>AI CIO Daily Report</b>\n"
        f"📅 Ngày: {date.today().strftime('%d/%m/%Y')}\n"
        f"🤖 Model: DeepSeek V4 Pro\n"
        f"📈 final score & regime : {score_val}\n"
        f"🎯 regime : {regime_val}"
    )

    print("[TG] Sending text message...")
    try:
        r = requests.post(
            f"{bot_api}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg_text, "parse_mode": "HTML"},
            timeout=30,
        )
        r.raise_for_status()
        print("[TG] Text sent.")
    except Exception as e:
        print(f"[ERROR] Telegram text failed: {e}")

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
        _create_pdf(report_text, str(PDF_PATH))
        print(f"[PDF] Saved: {PDF_PATH}")
    except ImportError:
        print("[ERROR] fpdf2 not installed. Please install: pip install fpdf2>=2.7.0")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] PDF creation failed: {e}")
        sys.exit(1)

    # 3. Parse score & regime
    score_val, regime_val = _parse_score_regime(report_text)
    print(f"[PARSE] Score: {score_val} | Regime: {regime_val}")

    # 4. Gửi Telegram
    _send_telegram(score_val, regime_val)

    print("[DONE]")
