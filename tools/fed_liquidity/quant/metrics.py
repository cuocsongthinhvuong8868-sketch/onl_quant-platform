"""
tools/fed_liquidity/quant/metrics.py
Core logic cho Fed Liquidity Monitor — không phụ thuộc Streamlit.

Workflow:
  1. fetch_fed_data(api_key) -> raw DataFrame [WALCL, WTREGEN, RRPONTSYD]
  2. process_liquidity_logic(df_raw) -> processed DataFrame với:
     Net_Liquidity, Impulse, Impulse_EMA, Z_Score, Signal
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Constants ──
FRED_SERIES = {
    "WALCL": "WALCL",              # Fed Total Assets (Balance Sheet)
    "WTREGEN": "WTREGEN",          # Treasury General Account
    "RRPONTSYD": "RRPONTSYD",      # Overnight Reverse Repo
}
RRP_MULTIPLIER = 1000              # RRPONTSYD raw units → match WALCL/TGA units (million $)
RESAMPLE_RULE = "W-WED"            # Weekly Wednesday (Fed data release)
EMA_SPAN = 4                       # ~1 tháng smoothing
ZSCORE_WINDOW = 52                 # 1 năm rolling
ADD_THRESHOLD = 1.0                # Z >= +1 + EMA > 0
CUT_THRESHOLD = -1.0               # Z <= -1 + EMA < 0
START_DATE = "2017-01-01"          # Bắt đầu monitor

OUTPUT_COLUMNS = [
    "WALCL", "WTREGEN", "RRPONTSYD",
    "Net_Liquidity", "Impulse", "Impulse_EMA",
    "Z_Score", "Signal",
]


def fetch_fed_data(api_key: str) -> pd.DataFrame:
    """
    Kéo 3 series FRED: WALCL, WTREGEN, RRPONTSYD.

    Parameters
    ----------
    api_key : str
        FRED API key.

    Returns
    -------
    pd.DataFrame index=Date, columns=[WALCL, WTREGEN, RRPONTSYD] (raw).

    Raises
    ------
    RuntimeError nếu kết nối FRED API thất bại.
    """
    try:
        from fredapi import Fred
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện 'fredapi'. Cài đặt: pip install fredapi"
        ) from e

    if not api_key:
        raise RuntimeError("FRED_API_KEY rỗng. Vui lòng cấu hình trong .env hoặc config.")

    fred = Fred(api_key=api_key)
    try:
        s_walcl = fred.get_series(FRED_SERIES["WALCL"])
        s_tga = fred.get_series(FRED_SERIES["WTREGEN"])
        s_rrp = fred.get_series(FRED_SERIES["RRPONTSYD"])
    except Exception as e:
        raise RuntimeError(f"Lỗi khi gọi FRED API: {e}") from e

    df = pd.DataFrame({
        "WALCL": s_walcl,
        "WTREGEN": s_tga,
        "RRPONTSYD": s_rrp,
    })
    df.index = pd.to_datetime(df.index)
    df.index.name = "DATE"
    return df


def process_liquidity_logic(df_raw: pd.DataFrame, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Xử lý logic thanh khoản Fed:
      - Chuẩn hoá RRPONTSYD × 1000 (đổi đơn vị)
      - Resample W-WED, forward-fill, dropna
      - Net_Liquidity = WALCL − WTREGEN − RRPONTSYD
      - Impulse = Net_Liquidity.diff()  (thay đổi tuần)
      - Impulse_EMA = Impulse.ewm(span=4)
      - Z_Score = (Impulse − mean_52w) / std_52w
      - Signal:
          ADD  : EMA > 0  AND  Z >= +1
          CUT  : EMA < 0  AND  Z <= -1
          HOLD : else

    Returns
    -------
    pd.DataFrame
        index=Date (datetime, weekly), columns trong OUTPUT_COLUMNS.
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = df_raw.copy()
    df["RRPONTSYD"] = df["RRPONTSYD"] * RRP_MULTIPLIER

    df = df.resample(RESAMPLE_RULE).last().ffill().dropna()
    df = df[df.index <= pd.Timestamp.today().normalize()]

    df["Net_Liquidity"] = df["WALCL"] - df["WTREGEN"] - df["RRPONTSYD"]
    df["Impulse"] = df["Net_Liquidity"].diff()
    df["Impulse_EMA"] = df["Impulse"].ewm(span=EMA_SPAN, adjust=False).mean()

    mean_w = df["Impulse"].rolling(window=ZSCORE_WINDOW).mean()
    std_w = df["Impulse"].rolling(window=ZSCORE_WINDOW).std()
    df["Z_Score"] = (df["Impulse"] - mean_w) / std_w.replace(0, np.nan)

    conditions = [
        (df["Impulse_EMA"] > 0) & (df["Z_Score"] >= ADD_THRESHOLD),
        (df["Impulse_EMA"] < 0) & (df["Z_Score"] <= CUT_THRESHOLD),
    ]
    df["Signal"] = np.select(conditions, ["ADD", "CUT"], default="HOLD")

    df = df[df.index >= pd.to_datetime(start_date)].copy()
    df = df.replace([np.inf, -np.inf], np.nan)

    return df[OUTPUT_COLUMNS]


def summarize_latest(df_processed: pd.DataFrame) -> dict:
    """
    Trích snapshot dòng cuối để hiển thị/AI report.
    """
    if df_processed is None or df_processed.empty:
        return {
            "date": "",
            "net_liquidity": 0.0,
            "impulse": 0.0,
            "impulse_ema": 0.0,
            "z_score": 0.0,
            "signal": "N/A",
            "walcl": 0.0,
            "wtregen": 0.0,
            "rrpontsyd": 0.0,
        }

    df_clean = df_processed.dropna(subset=["Z_Score"])
    if df_clean.empty:
        df_clean = df_processed

    latest = df_clean.iloc[-1]
    return {
        "date": df_clean.index[-1].strftime("%Y-%m-%d"),
        "net_liquidity": float(latest["Net_Liquidity"]),
        "impulse": float(latest["Impulse"]) if pd.notna(latest["Impulse"]) else 0.0,
        "impulse_ema": float(latest["Impulse_EMA"]) if pd.notna(latest["Impulse_EMA"]) else 0.0,
        "z_score": float(latest["Z_Score"]) if pd.notna(latest["Z_Score"]) else 0.0,
        "signal": str(latest["Signal"]),
        "walcl": float(latest["WALCL"]),
        "wtregen": float(latest["WTREGEN"]),
        "rrpontsyd": float(latest["RRPONTSYD"]),
    }
