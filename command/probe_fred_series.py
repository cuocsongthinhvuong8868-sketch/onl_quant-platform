"""
command/probe_fred_series.py
Diagnostic: test xem FRED series IDs còn data hay đã bị pull (license restriction 2021).

Usage:
    python command/probe_fred_series.py

Cần FRED_API_KEY trong .env hoặc env var.
"""
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except ImportError:
    pass

from fredapi import Fred

CANDIDATES = [
    # Confirmed working baselines
    "VIXCLS",                # CBOE Volatility Index
    "BAMLH0A0HYM2",          # Broad US HY OAS — chắc chắn còn live
    # Sub-rating OAS (cái bị nghi pull 2021)
    "BAMLH0A1HYBB",          # BB US HY OAS
    "BAMLH0A2HYB",           # B US HY OAS
    "BAMLH0A3HYC",           # CCC & Lower US HY OAS
    # Effective Yield variants (đôi khi còn khi OAS bị pull)
    "BAMLH0A0HYM2EY",        # Broad HY Effective Yield
    "BAMLH0A3HYCEY",         # CCC Effective Yield
]


def main():
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("ERROR: FRED_API_KEY không có trong env. Kiểm tra .env file.")
        sys.exit(1)

    fred = Fred(api_key=api_key)

    print(f"{'SERIES_ID':22s} | {'N_OBS':>7s} | {'LATEST':>12s} | {'STATUS'}")
    print("-" * 70)

    for code in CANDIDATES:
        try:
            s = fred.get_series(code)
            n = int(s.dropna().shape[0])
            if n == 0:
                print(f"{code:22s} | {n:>7d} | {'—':>12s} | EMPTY (likely pulled)")
            else:
                latest = s.dropna().iloc[-1]
                latest_date = s.dropna().index[-1].strftime("%Y-%m-%d")
                print(f"{code:22s} | {n:>7d} | {latest:>12.4f} | OK ({latest_date})")
        except Exception as e:
            msg = str(e).strip()
            if len(msg) > 40:
                msg = msg[:40] + "…"
            print(f"{code:22s} | {'?':>7s} | {'—':>12s} | ERROR: {msg}")


if __name__ == "__main__":
    main()
