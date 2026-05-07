import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

VN30_LIST = [
    'ACB','BCM','BID','BVH','CTG','FPT','GAS','GVR','HDB','HPG',
    'MBB','MSN','MWG','PLX','POW','SAB','SHB','SSB','SSI','STB',
    'TCB','TPB','VCB','VHM','VIB','VIC','VJC','VNM','VPB','VRE'
]


def calculate_esr(df_close: pd.DataFrame, df_index: pd.DataFrame, ma_period: int = 125, pca_window: int = 60):
    tickers = [t for t in VN30_LIST if t in df_close.columns]
    if len(tickers) < 10:
        raise ValueError("Không đủ mã VN30 trong market_data để tính ESR.")

    prices = df_close[tickers].sort_index().ffill()
    rets = prices.pct_change().dropna(how="all")

    idx_col = "VNINDEX" if "VNINDEX" in df_index.columns else df_index.columns[0]
    idx = df_index[[idx_col]].copy().rename(columns={idx_col: "INDEX"}).sort_index().ffill()

    common = idx.index.intersection(rets.index)
    idx = idx.loc[common]
    rets = rets.loc[common]
    if len(common) < (pca_window + 30):
        raise ValueError("Không đủ lịch sử giao nhau giữa index và cổ phiếu.")

    idx_ret = idx["INDEX"].pct_change()
    s_vol = idx_ret.rolling(20).std() * np.sqrt(252)

    # proxy leverage: downside participation ratio
    down_ratio = (rets.lt(0).sum(axis=1) / rets.notna().sum(axis=1)).rolling(5).mean()

    s_cor_vals = []
    for i in range(len(rets)):
        if i < pca_window:
            s_cor_vals.append(np.nan)
            continue
        w = rets.iloc[i - pca_window:i].fillna(0)
        try:
            pca = PCA(n_components=1)
            pca.fit(w)
            s_cor_vals.append(float(pca.explained_variance_ratio_[0]))
        except Exception:
            s_cor_vals.append(np.nan)
    s_cor = pd.Series(s_cor_vals, index=rets.index)

    # proxy liquidity stress via cross-sectional abs-return
    s_liq = rets.abs().median(axis=1).rolling(20).mean()

    # valuation proxy from inverse index level
    s_val = -(1.0 / (idx["INDEX"] / 100.0))

    pillars = pd.DataFrame({
        "S_VOL": s_vol,
        "S_LEV": down_ratio,
        "S_COR": s_cor,
        "S_LIQ": s_liq,
        "S_VAL": s_val,
    }).dropna()

    rank = pillars.rank(pct=True)
    pca_final = PCA(n_components=1).fit(rank)
    weights = np.abs(pca_final.components_[0])
    weights = weights / weights.sum()

    out = pillars.copy()
    out["SSI_Index"] = (rank * weights).sum(axis=1)
    out["INDEX_Close"] = idx.loc[out.index, "INDEX"]
    out[f"MA{ma_period}"] = out["INDEX_Close"].rolling(ma_period).mean()
    out = out.dropna()

    w = pd.Series(weights, index=["S_VOL", "S_LEV", "S_COR", "S_LIQ", "S_VAL"])
    return out, w
