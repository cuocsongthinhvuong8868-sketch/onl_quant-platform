import pandas as pd
from vnstock import Quote
from pathlib import Path
import numpy as np

print("Fetching VN30F1M...")
df = None
try:
    df = Quote(symbol="VN30F1M", source="VCI").history(start="2026-06-02", end="2026-06-06", interval="1D")
except Exception as e:
    print("VCI failed:", e)

if df is None or df.empty:
    try:
        df = Quote(symbol="VN30F1M", source="KBS").history(start="2026-06-02", end="2026-06-06", interval="1D")
    except Exception as e:
        print("KBS failed:", e)

if df is not None and not df.empty:
    print("Fetched df:")
    print(df)
    
    df = df.set_index("time")
    df.index = pd.to_datetime(df.index).normalize().tz_localize(None)
    df = df[~df.index.duplicated(keep="last")]
    
    p1 = Path("data_lake/market_data.csv")
    if p1.exists():
        mdata = pd.read_csv(p1, index_col=0, parse_dates=True)
        mdata.loc[df.index, "VN30F1M"] = df["close"]
        mdata.to_csv(p1)
        print("Updated market_data.csv successfully.")
        
    p2 = Path("data_lake/market_volume.csv")
    if p2.exists() and "volume" in df.columns:
        mvol = pd.read_csv(p2, index_col=0, parse_dates=True)
        mvol.loc[df.index, "VN30F1M"] = df["volume"]
        mvol.to_csv(p2)
        print("Updated market_volume.csv successfully.")
else:
    print("Failed to fetch VN30F1M data.")
