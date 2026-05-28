import pandas as pd
from vnstock import Finance
import sys

HOSE_BANKS = [
    "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "ACB", "SSB",
    "SHB", "HDB", "VIB", "LPB", "EIB", "OCB", "MSB", "TPB",
]

all_data = []

for bank in HOSE_BANKS:
    try:
        fin = Finance(symbol=bank, source="KBS")
        df_ratio = fin.ratio(period="quarter")
        if df_ratio is not None and not df_ratio.empty:
            df_ratio.to_csv(f"scratch/{bank}_ratio_KBS.csv", index=False, encoding='utf-8')
        
        df_bs = fin.balance_sheet(period="quarter", lang="vi")
        if df_bs is not None and not df_bs.empty:
            df_bs.to_csv(f"scratch/{bank}_bs_KBS.csv", index=False, encoding='utf-8')
            
        print(f"Downloaded {bank}")
    except Exception as e:
        print(f"Error {bank}: {e}")
        
