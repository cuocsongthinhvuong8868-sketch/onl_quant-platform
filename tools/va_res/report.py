import pandas as pd
import polars as pl
import numpy as np
from tools.va_res.quant.metrics import SystemicRiskEngine

VN30_TICKERS = ['ACB', 'BCM', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 'MBB', 'MSN', 'MWG', 'PLX', 'POW', 'SAB', 'SHB', 'SSB', 'SSI', 'STB', 'TCB', 'TPB', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VRE']

MARKET_TICKERS = {
    'Ngân Hàng': ['VCB', 'BID', 'CTG', 'MBB', 'TCB', 'VPB', 'ACB', 'STB', 'HDB', 'VIB', 'SHB', 'TPB', 'SSB', 'LPB', 'MSB', 'OCB', 'EIB'],
    'Bất Động Sản': ['VIC', 'VHM', 'VRE', 'NVL', 'DIG', 'DXG', 'KDH', 'NLG', 'PDR', 'SCR', 'HDG', 'CRE', 'IJC', 'HQC', 'CEO'],
    'Chứng Khoán': ['SSI', 'VND', 'VCI', 'HCM', 'FTS', 'BSI', 'VIX', 'CTS', 'ORS', 'AGR', 'VDS'], 
    'Thép / Vật Liệu': ['HPG', 'HSG', 'NKG', 'HT1', 'BCC', 'SMC', 'TLH', 'BMP', 'KSB'],
    'Xây Dựng / Đầu Tư Công': ['VCG', 'CTD', 'CII', 'HHV', 'LCG', 'FCN', 'PC1'],
    'Hóa Chất / Phân Bón': ['DGC', 'DPM', 'DCM', 'CSV', 'LAS'],
    'Dầu Khí': ['GAS', 'PLX', 'PVD', 'PVT', 'PVS', 'BSR', 'CNG', 'VIP', 'VTO'], 
    'Bán Lẻ': ['MWG', 'PNJ', 'FRT', 'DGW', 'PET', 'HAX'],
    'Khu Công Nghiệp': ['BCM', 'KBC', 'SZC', 'VGC', 'PHR', 'ITA', 'D2D', 'IDC'],
    'Công Nghệ': ['FPT', 'CMG', 'ELC', 'SAM', 'VGI'],
    'Cảng Biển / Logistics': ['GMD', 'HAH', 'VSC', 'TCL', 'VOS'],
    'Nông Nghiệp / Thủy Sản': ['VHC', 'ANV', 'DBC', 'HAG', 'HNG', 'FMC', 'IDI', 'PAN', 'BAF'],
    'Tiện Ích': ['POW', 'REE', 'NT2', 'GEG', 'VSH', 'BWE']
}
ALL_MARKET_TICKERS = [ticker for sublist in MARKET_TICKERS.values() for ticker in sublist]

def snapshot(df_price_full: pd.DataFrame, load_custom=None) -> dict:
    """
    Tính toán Stress Index (VN30) và Complacency Index (Market) cho ngày mới nhất
    bằng SystemicRiskEngine (Polars/Numba backend).
    """
    date_str = df_price_full.index[-1].strftime('%d/%m/%Y')
    
    # Prepare Polars Dataframe
    df_price_reset = df_price_full.reset_index()
    date_col = df_price_reset.columns[0]
    
    engine = SystemicRiskEngine()
    
    # 1. Systemic Risk (VN30)
    available_vn30 = [t for t in VN30_TICKERS if t in df_price_reset.columns]
    df_vn30_pandas = df_price_reset[[date_col] + available_vn30]
    df_vn30_pl = pl.from_pandas(df_vn30_pandas)
    
    df_metrics30 = engine.calculate_risk_metrics(df_vn30_pl, method='cornish_fisher')
    df_contagion = engine.calculate_contagion_index(df_metrics30)
    
    latest_stress = df_contagion.to_pandas().iloc[-1]['Contagion_Index']
    
    # Top 3 tickers breaching VaR by most margin
    latest_date_30 = df_metrics30[date_col].max()
    df_latest_30 = df_metrics30.filter(pl.col(date_col) == latest_date_30).to_pandas()
    df_latest_30['breach_margin'] = df_latest_30['VaR'] - df_latest_30['return']
    breached_30 = df_latest_30[df_latest_30['return'] < df_latest_30['VaR']]
    
    if not breached_30.empty:
        top_3_crash = breached_30.sort_values(by='breach_margin', ascending=False).head(3)['ticker'].tolist()
        breached_count = len(breached_30)
    else:
        top_3_crash = ["Không có"]
        breached_count = 0
        
    # 2. Complacency Index (Market Mispricing)
    available_tickers = [t for t in ALL_MARKET_TICKERS if t in df_price_reset.columns]
    cols_to_select = [date_col] + available_tickers
    
    if 'VNINDEX' in df_price_reset.columns:
        cols_to_select.append('VNINDEX')
        df_mkt_pandas = df_price_reset[cols_to_select]
    else:
        df_mkt_pandas = df_price_reset[cols_to_select].copy()
        try:
            from shared.data_loader import load_custom
            vnindex_df = load_custom("vnindex_cache.csv").reset_index()
            idx_col = "VNINDEX" if "VNINDEX" in vnindex_df.columns else vnindex_df.columns[1]
            vni_date_col = vnindex_df.columns[0]
            df_mkt_pandas = df_mkt_pandas.merge(
                vnindex_df[[vni_date_col, idx_col]].rename(columns={idx_col: 'VNINDEX', vni_date_col: date_col}),
                on=date_col, how='left'
            )
            if df_mkt_pandas['VNINDEX'].isna().all():
                df_mkt_pandas['VNINDEX'] = df_mkt_pandas[available_tickers].mean(axis=1)
        except FileNotFoundError:
            df_mkt_pandas['VNINDEX'] = df_mkt_pandas[available_tickers].mean(axis=1)
        
    df_mkt_pl = pl.from_pandas(df_mkt_pandas)
    
    df_metricsM = engine.calculate_risk_metrics(df_mkt_pl, method='cornish_fisher')
    df_complacency = engine.calculate_complacency_index(df_metricsM)
    
    df_comp_agg = df_complacency.group_by(date_col).agg(
        (pl.col("is_mispriced").sum() / len(available_tickers) * 100).alias("Complacency_Index")
    ).sort(date_col)
    
    latest_complacency = df_comp_agg.to_pandas().iloc[-1]['Complacency_Index']
    
    # Top 3 mispriced tickers by tightest spread
    df_status = engine.get_latest_risk_status(df_complacency).to_pandas()
    mispriced_df = df_status[df_status['Status'] == 'Risk Mispriced']
    
    if not mispriced_df.empty:
        top_3_mispriced = mispriced_df.sort_values(by='Spread', ascending=True).head(3)['ticker'].tolist()
        mispriced_count = len(mispriced_df)
    else:
        top_3_mispriced = ["Không có"]
        mispriced_count = 0
        
    return {
        "date": date_str,
        "stress_index": float(latest_stress),
        "complacency_index": float(latest_complacency),
        "top_3_crash": top_3_crash,
        "top_3_mispriced": top_3_mispriced,
        "breached_count": breached_count,
        "mispriced_count": mispriced_count
    }
