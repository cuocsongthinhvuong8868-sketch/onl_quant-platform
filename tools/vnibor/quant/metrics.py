"""
tools/vnibor/quant/metrics.py
Core logic for Vietnam Interbank Offered Rate (VNIBOR) Analysis.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from config import DATA_LAKE

VNIBOR_FILE = "LaiSuatLienNganHang_Wichart.csv"
ROLLING_WINDOW = 252  # ~1 year of business days

OUTPUT_COLUMNS = [
    "Overnight_ON", "1_Week", "2_Weeks",
    "ON_Impulse", "ON_ZScore", "ON_Percentile",
    "Spread_1W_ON", "Spread_2W_ON", "Regime", "Signal"
]

def load_vnibor_data() -> pd.DataFrame:
    """Đọc dữ liệu lãi suất liên ngân hàng từ CSV và chuẩn hoá."""
    path = DATA_LAKE / VNIBOR_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy file dữ liệu: {path}\n"
            "Vui lòng chạy: python command/update_vnibor.py"
        )
    
    # Đọc CSV với cột Ngày làm index
    df = pd.read_csv(path, parse_dates=["Ngày"])
    df = df.rename(columns={
        "Ngày": "DATE",
        "Lãi suất qua đêm _ON (%)": "Overnight_ON",
        "Lãi suất 1 tuần (%)": "1_Week",
        "Lãi suất 2 tuần (%)": "2_Weeks"
    })
    
    df = df.set_index("DATE").sort_index()
    
    # Convert numeric
    for col in ["Overnight_ON", "1_Week", "2_Weeks"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
    # Forward fill missing values if any
    df = df.ffill().bfill()
    return df

def process_vnibor_logic(df_raw: pd.DataFrame, window: int = ROLLING_WINDOW) -> pd.DataFrame:
    """
    Tính toán các chỉ số vĩ mô cho VNIBOR:
      - ON_Impulse: Thay đổi điểm phần trăm (DoD change) của lãi suất qua đêm
      - ON_ZScore: Rolling Z-score của lãi suất qua đêm (window = 252 ngày)
      - ON_Percentile: Rolling Percentile của lãi suất qua đêm (window = 252 ngày)
      - Spread_1W_ON: Chênh lệch kỳ hạn 1 tuần - qua đêm (Spread 1W - ON)
      - Spread_2W_ON: Chênh lệch kỳ hạn 2 tuần - qua đêm (Spread 2W - ON)
      - Regime: EASY (<25%), NORMAL (25-50%), ELEVATED (50-75%), TIGHT (>=75%)
      - Signal: Cảnh báo thanh khoản dựa trên mức lãi suất, z-score và đường cong lợi suất (ngược)
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
        
    df = df_raw.copy()
    
    # 1. Tính toán chênh lệch (Spreads)
    df["Spread_1W_ON"] = df["1_Week"] - df["Overnight_ON"]
    df["Spread_2W_ON"] = df["2_Weeks"] - df["Overnight_ON"]
    
    # 2. Tính Impulse (thay đổi hàng ngày)
    df["ON_Impulse"] = df["Overnight_ON"].diff()
    
    # 3. Tạo chuỗi mượt 5 phiên (Trung bình trượt 5 phiên) để giảm nhiễu thanh khoản cực ngắn hạn
    df["ON_5D_Mean"] = df["Overnight_ON"].rolling(window=5, min_periods=1).mean()
    
    # 4. Tính Rolling Mean & Std của chuỗi mượt 5 phiên để tính Z-Score
    rolling_mean_5d = df["ON_5D_Mean"].rolling(window=window, min_periods=30).mean()
    rolling_std_5d = df["ON_5D_Mean"].rolling(window=window, min_periods=30).std()
    df["ON_ZScore"] = (df["ON_5D_Mean"] - rolling_mean_5d) / rolling_std_5d.replace(0, np.nan)
    
    # 5. Tính Rolling Percentile Rank của chuỗi mượt 5 phiên
    def get_rolling_percentile(s: pd.Series, w: int) -> pd.Series:
        return s.rolling(window=w, min_periods=30).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 0 else np.nan, 
            raw=True
        )
        
    df["ON_Percentile"] = get_rolling_percentile(df["ON_5D_Mean"], window)
    
    # 6. Phân loại Regime dựa trên ON_Percentile mượt 5 phiên
    # EASY: < 25%, NORMAL: 25% - 50%, ELEVATED: 50% - 75%, TIGHT: >= 75%
    regime_conditions = [
        df["ON_Percentile"] >= 0.75,
        (df["ON_Percentile"] >= 0.50) & (df["ON_Percentile"] < 0.75),
        (df["ON_Percentile"] >= 0.25) & (df["ON_Percentile"] < 0.50),
        df["ON_Percentile"] < 0.25
    ]
    regime_labels = ["TIGHT", "ELEVATED", "NORMAL", "EASY"]
    df["Regime"] = np.select(regime_conditions, regime_labels, default="NORMAL")
    
    # 7. Tín hiệu Liquidity (Signal) dựa trên các chỉ số mượt và spreads
    # STRESS: Lãi suất ON cực cao (> 6.0%) HOẶC Z-Score mượt cao (> 1.5) HOẶC Đường cong lợi suất đảo ngược (Spread_1W_ON < 0)
    # WARNING: Lãi suất ON tăng nhanh (Impulse > 1.0% trong ngày) HOẶC Z-score mượt > 1.0
    # ACCOMMODATIVE: Lãi suất ON rất thấp (< 2.0%)
    # NEUTRAL: bình thường
    signal_conditions = [
        (df["Overnight_ON"] >= 6.0) | (df["ON_ZScore"] >= 1.5) | (df["Spread_1W_ON"] < 0),
        (df["ON_ZScore"] >= 1.0) | (df["ON_Impulse"] >= 1.0),
        (df["Overnight_ON"] <= 2.0)
    ]
    signal_labels = ["STRESS", "WARNING", "ACCOMMODATIVE"]
    df["Signal"] = np.select(signal_conditions, signal_labels, default="NEUTRAL")
    
    # Fill NaNs with sensible defaults or drop them
    df = df.replace([np.inf, -np.inf], np.nan)
    return df

def summarize_latest(df_processed: pd.DataFrame) -> dict:
    """Tạo báo cáo nhanh cho phiên gần nhất."""
    if df_processed is None or df_processed.empty:
        return {
            "date": "N/A", "overnight": 0.0, "w1": 0.0, "w2": 0.0,
            "impulse": 0.0, "z_score": 0.0, "percentile": 0.0,
            "spread_1w": 0.0, "spread_2w": 0.0, "regime": "N/A", "signal": "N/A"
        }
        
    latest = df_processed.iloc[-1]
    return {
        "date": df_processed.index[-1].strftime("%Y-%m-%d"),
        "overnight": float(latest["Overnight_ON"]),
        "w1": float(latest["1_Week"]),
        "w2": float(latest["2_Weeks"]),
        "impulse": float(latest["ON_Impulse"]) if pd.notna(latest["ON_Impulse"]) else 0.0,
        "z_score": float(latest["ON_ZScore"]) if pd.notna(latest["ON_ZScore"]) else 0.0,
        "percentile": float(latest["ON_Percentile"]) if pd.notna(latest["ON_Percentile"]) else 0.0,
        "spread_1w": float(latest["Spread_1W_ON"]) if pd.notna(latest["Spread_1W_ON"]) else 0.0,
        "spread_2w": float(latest["Spread_2W_ON"]) if pd.notna(latest["Spread_2W_ON"]) else 0.0,
        "regime": str(latest["Regime"]),
        "signal": str(latest["Signal"])
    }
