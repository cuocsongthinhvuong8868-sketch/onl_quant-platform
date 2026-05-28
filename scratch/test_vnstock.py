import pandas as pd
from vnstock import Finance, Listing

try:
    print("Listing industries:")
    listing = Listing()
    # see what methods exist
    print(dir(listing))
except Exception as e:
    print("Error listing:", e)

try:
    fin = Finance(symbol="VCB", source="KBS")
    df = fin.ratio(period="quarter")
    print("\nRatio items:")
    if df is not None and not df.empty:
        print(df['item'].unique())
    else:
        print("Ratio df empty")
except Exception as e:
    print("Error ratio:", e)

try:
    fin = Finance(symbol="VCB", source="TCBS")
    print("\nTCBS Ratio items:")
    df_tcbs = fin.ratio(period="quarter")
    if df_tcbs is not None and not df_tcbs.empty:
        print(df_tcbs['item'].unique())
    else:
        print("TCBS Ratio df empty")
except Exception as e:
    print("Error tcbs ratio:", e)
