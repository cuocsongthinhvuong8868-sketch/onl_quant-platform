import pandas as pd


def compute_breadth(df_prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    prices = df_prices.sort_index().ffill()

    ma20 = prices.rolling(window=20).mean()
    ma60 = prices.rolling(window=60).mean()
    ma125 = prices.rolling(window=125).mean()
    ma252 = prices.rolling(window=252).mean()

    b20 = (prices > ma20).sum(axis=1)
    b60 = (prices > ma60).sum(axis=1)
    b125 = (prices > ma125).sum(axis=1)
    b252 = (prices > ma252).sum(axis=1)

    breadth = pd.DataFrame(
        {
            "> MA20": b20,
            "> MA60": b60,
            "> MA125": b125,
            "> MA252": b252,
        }
    ).dropna()

    masks = {
        "> MA20": prices > ma20,
        "> MA60": prices > ma60,
        "> MA125": prices > ma125,
        "> MA252": prices > ma252,
    }
    return breadth, masks


def top10_by_volume(df_volumes: pd.DataFrame | None, latest_date: pd.Timestamp, valid_stocks) -> pd.DataFrame:
    if df_volumes is None or df_volumes.empty:
        return pd.DataFrame({"Mã CP": [], "Khối lượng": []})

    cols = [c for c in valid_stocks if c in df_volumes.columns]
    if not cols or latest_date not in df_volumes.index:
        return pd.DataFrame({"Mã CP": [], "Khối lượng": []})

    vols = pd.to_numeric(df_volumes.loc[latest_date, cols], errors="coerce").dropna()
    top = vols.sort_values(ascending=False).head(10)
    out = pd.DataFrame({"Mã CP": top.index, "Khối lượng": top.values})
    out["Khối lượng"] = out["Khối lượng"].map(lambda x: f"{int(x):,}")
    return out
