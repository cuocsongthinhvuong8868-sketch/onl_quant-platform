import os
import json
import logging
import time
from datetime import datetime, timedelta
import pandas as pd

logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO").upper(), format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

try:
    from vnstock import Quote
except ImportError:
    logger.exception("vnstock is not installed. Run: pip install -U vnstock")
    raise SystemExit(1)

def main():
    tickers = [
        "ABB", "ACB", "BAB", "BID", "BVB", "CTG", "EIB", "HDB", 
        "KLB", "LPB", "MBB", "MSB", "NAB", "NVB", "OCB", "PGB", 
        "SGB", "SHB", "SSB", "TCB", "TPB", "VAB", "VCB", "VIB", "VPB"
    ]
    
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    
    prices = {}
    print(f"Fetching realtime prices for {len(tickers)} banks (Wait ~{len(tickers)*3}s due to rate limit)...")
    
    for i, ticker in enumerate(tickers):
        try:
            df = Quote(symbol=ticker, source="VCI").history(start=start, end=end, interval="1D")
            if df is not None and not df.empty:
                # Multiply by 1000 if vnstock3 returns thousands, usually vnstock returns actual price or /1000
                price = float(df.iloc[-1]["close"]) 
                
                # vnstock3 often returns price in VND (e.g. 24000) or thousands (e.g. 24.0)
                # Let's see if it's < 1000, multiply by 1000 to get VND
                if price < 1000:
                    price *= 1000
                    
                prices[ticker] = price
                print(f"[{i+1}/{len(tickers)}] {ticker}: {price:,.0f} VND")
            else:
                print(f"[{i+1}/{len(tickers)}] {ticker}: No data")
        except Exception:
            logger.exception("[%s/%s] %s: price fetch failed", i + 1, len(tickers), ticker)
            
        time.sleep(3) # Ensure we don't exceed 20 req/min
        
    os.makedirs("data/raw", exist_ok=True)
    with open("data/raw/realtime_prices.json", "w") as f:
        json.dump(prices, f)
        
    print("Done! Saved realtime prices.")

if __name__ == "__main__":
    main()
