import pandas as pd
from vnstock import Finance
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

print("Fetching VCB ratio...")
fin = Finance(symbol="VCB", source="VCI") # VCI or KBS
df_ratio = fin.ratio(period="quarter")

if df_ratio is not None and not df_ratio.empty:
    df_ratio.to_csv("scratch/vcb_ratio.csv", index=False, encoding='utf-8')
    print("Ratio saved.")

print("Fetching VCB balance sheet...")
df_bs = fin.balance_sheet(period="quarter", lang="vi")
if df_bs is not None and not df_bs.empty:
    df_bs.to_csv("scratch/vcb_bs.csv", index=False, encoding='utf-8')
    print("Balance sheet saved.")
