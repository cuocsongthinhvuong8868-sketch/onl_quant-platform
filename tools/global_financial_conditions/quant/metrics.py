"""
tools/global_financial_conditions/quant/metrics.py
Core logic cho Global Financial Conditions Monitor (GFCM).

4 indicators:
  - VIX  (CBOE Volatility Index)            : FRED VIXCLS
  - MOVE (ICE BofAML US Bond Vol Estimate)  : Yahoo ^MOVE
  - HY OAS (ICE BofA US HY Index OAS)       : FRED BAMLH0A0HYM2
  - CCC OAS (ICE BofA CCC & Lower HY OAS)   : FRED BAMLH0A3HYCM
  - Derived: Credit Quality Spread = CCC − HY

Pipeline:
  1. fetch_raw_data(fred_api_key) -> DataFrame [VIX, MOVE, HY_OAS, CCC_OAS]
  2. process_gfcm_logic(df_raw) -> DataFrame với:
       * Per-series rolling z-score & percentile rank 756d (3Y)
       * Credit Quality Spread (CCC − HY) + percentile
       * Static PCA (PC1 = stress, PC2 = divergence)
       * PC1 rolling percentile 3Y
       * Regime classification (STRESS / ELEVATED / CALM)
       * Driver flag (EQUITY / RATES / HY_CREDIT / CCC_CREDIT / BROAD_STRESS / NO_STRESS)

Quant layer KHÔNG import Streamlit. Errors RAISE thay vì swallow.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ── Constants ──
FRED_SERIES = {
    "VIX": "VIXCLS",
    "HY_OAS": "BAMLH0A0HYM2",
    "CCC_OAS": "BAMLH0A3HYCM",
}
YAHOO_MOVE_TICKER = "^MOVE"

START_DATE = "2003-01-01"       # MOVE Yahoo coverage starts ~2003
ROLLING_WINDOW = 756            # 3 năm trading days

PCT_STRESS = 0.80               # PC1_pct ≥ 0.80 → STRESS
PCT_ELEVATED = 0.50             # 0.50 ≤ PC1_pct < 0.80 → ELEVATED, dưới = CALM
PCT_DRIVER_HIGH = 0.80          # Driver flag threshold per-series

RAW_COLUMNS = ["VIX", "MOVE", "HY_OAS", "CCC_OAS"]

OUTPUT_COLUMNS = [
    # Raw levels
    "VIX", "MOVE", "HY_OAS", "CCC_OAS",
    # Derived
    "Credit_Quality_Spread",            # CCC_OAS − HY_OAS
    # Z-scores rolling 3Y
    "VIX_z", "MOVE_z", "HY_z", "CCC_z",
    # Percentile rank rolling 3Y
    "VIX_pct", "MOVE_pct", "HY_pct", "CCC_pct",
    "CQS_pct",
    # PCA outputs
    "PC1", "PC2", "PC1_pct",
    # Classification
    "Regime", "Driver",
]


# ────────────────────────────────────────────────────────────────────────────
# Fetchers
# ────────────────────────────────────────────────────────────────────────────

def fetch_fred_series(api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Pull 3 FRED series: VIXCLS, BAMLH0A0HYM2, BAMLH0A3HYCM.

    Returns
    -------
    pd.DataFrame index=Date (datetime), columns=[VIX, HY_OAS, CCC_OAS].
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
    cols = {}
    for col, code in FRED_SERIES.items():
        try:
            s = fred.get_series(code, observation_start=start_date)
        except Exception as e:
            raise RuntimeError(f"Lỗi khi gọi FRED API ({code}): {e}") from e
        s.index = pd.to_datetime(s.index)
        cols[col] = s

    df = pd.DataFrame(cols).sort_index()
    df.index.name = "DATE"
    return df


def fetch_move_yahoo(start_date: str = START_DATE) -> pd.Series:
    """
    Pull ^MOVE từ Yahoo Finance qua yfinance.

    Returns
    -------
    pd.Series index=Date (datetime), name='MOVE', daily close.
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện 'yfinance'. Cài đặt: pip install yfinance"
        ) from e

    try:
        df = yf.download(
            YAHOO_MOVE_TICKER,
            start=start_date,
            progress=False,
            auto_adjust=False,
        )
    except Exception as e:
        raise RuntimeError(f"Lỗi khi tải MOVE từ Yahoo Finance: {e}") from e

    if df is None or df.empty:
        raise RuntimeError(
            "Yahoo Finance trả về dữ liệu rỗng cho ^MOVE. "
            "Có thể ticker tạm bị rate-limit hoặc network lỗi — thử lại sau."
        )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Close" not in df.columns:
        raise RuntimeError(f"Yahoo response thiếu cột 'Close'. Có: {list(df.columns)}")

    s = df["Close"].astype(float)
    s.index = pd.to_datetime(s.index)
    s.name = "MOVE"
    return s


def fetch_raw_data(fred_api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Merge VIX + MOVE + HY_OAS + CCC_OAS thành 1 DataFrame.
    Outer-join (giữ tất cả ngày), forward-fill từng cột tới 5 phiên để
    bù holiday lệch giữa US equity và bond market. Inner dropna ở step
    processing sau.
    """
    df_fred = fetch_fred_series(fred_api_key, start_date=start_date)
    s_move = fetch_move_yahoo(start_date=start_date)

    df = df_fred.join(s_move, how="outer").sort_index()
    df.index.name = "DATE"
    df = df.ffill(limit=5)
    return df[RAW_COLUMNS]


# ────────────────────────────────────────────────────────────────────────────
# Per-series transforms
# ────────────────────────────────────────────────────────────────────────────

def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    mean = s.rolling(window=window, min_periods=window).mean()
    std = s.rolling(window=window, min_periods=window).std().replace(0, np.nan)
    return (s - mean) / std


def _rolling_pct_rank(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window=window, min_periods=window).rank(pct=True)


# ────────────────────────────────────────────────────────────────────────────
# PCA
# ────────────────────────────────────────────────────────────────────────────

def fit_static_pca(df_z: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Fit PCA 1 lần trên toàn bộ z-score history → project mọi ngày.

    Sign convention: force PC1 loading trên VIX_z dương → PC1 cao = stress.
    PC2 sign convention: force loading trên HY_z dương → PC2 cao = credit-tilt.

    Parameters
    ----------
    df_z : pd.DataFrame
        Columns [VIX_z, MOVE_z, HY_z, CCC_z], rows aligned daily.

    Returns
    -------
    df_pc : pd.DataFrame [PC1, PC2] aligned tới input index (NaN ở chỗ z thiếu).
    meta  : dict {
        "loadings": pd.DataFrame (rows=4 series, cols=[PC1, PC2]),
        "explained_variance_ratio": [pc1_var, pc2_var],
        "n_samples_fit": int,
        "pc1_interpretation": str,
        "pc2_interpretation": str,
    }
    """
    try:
        from sklearn.decomposition import PCA
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện 'scikit-learn'. Cài đặt: pip install scikit-learn"
        ) from e

    z_cols = ["VIX_z", "MOVE_z", "HY_z", "CCC_z"]
    df_clean = df_z[z_cols].dropna()

    # PCA cần ≥ n_features+1 samples; require ≥ 60 cho fit có ý nghĩa.
    min_pca_samples = 60
    if len(df_clean) < min_pca_samples:
        return (
            pd.DataFrame(index=df_z.index, columns=["PC1", "PC2"], dtype=float),
            {
                "loadings": None,
                "explained_variance_ratio": [],
                "n_samples_fit": len(df_clean),
                "pc1_interpretation": "Insufficient data",
                "pc2_interpretation": "Insufficient data",
            },
        )

    pca = PCA(n_components=2)
    pcs = pca.fit_transform(df_clean.values)
    components = pca.components_.copy()

    vix_idx = z_cols.index("VIX_z")
    if components[0, vix_idx] < 0:
        pcs[:, 0] *= -1
        components[0] *= -1

    hy_idx = z_cols.index("HY_z")
    if components[1, hy_idx] < 0:
        pcs[:, 1] *= -1
        components[1] *= -1

    df_pc_clean = pd.DataFrame(pcs, index=df_clean.index, columns=["PC1", "PC2"])
    df_pc = df_pc_clean.reindex(df_z.index)

    loadings_df = pd.DataFrame(
        components.T,
        index=z_cols,
        columns=["PC1", "PC2"],
    )

    pc2_load = loadings_df["PC2"]
    vol_avg = (pc2_load["VIX_z"] + pc2_load["MOVE_z"]) / 2
    credit_avg = (pc2_load["HY_z"] + pc2_load["CCC_z"]) / 2
    if credit_avg > vol_avg:
        pc2_interp = "PC2 cao = credit-driven; PC2 thấp = vol-driven"
    else:
        pc2_interp = "PC2 cao = vol-driven; PC2 thấp = credit-driven"

    meta = {
        "loadings": loadings_df,
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
        "n_samples_fit": len(df_clean),
        "pc1_interpretation": "PC1 cao = financial conditions tighten (stress)",
        "pc2_interpretation": pc2_interp,
    }
    return df_pc, meta


# ────────────────────────────────────────────────────────────────────────────
# Regime & Driver
# ────────────────────────────────────────────────────────────────────────────

def _classify_regime(pc1_pct: float) -> str:
    if pd.isna(pc1_pct):
        return "N/A"
    if pc1_pct >= PCT_STRESS:
        return "STRESS"
    if pc1_pct >= PCT_ELEVATED:
        return "ELEVATED"
    return "CALM"


def _classify_driver(
    vix_pct: float, move_pct: float, hy_pct: float, ccc_pct: float
) -> str:
    pcts = {
        "EQUITY": vix_pct,
        "RATES": move_pct,
        "HY_CREDIT": hy_pct,
        "CCC_CREDIT": ccc_pct,
    }
    valid = {k: v for k, v in pcts.items() if pd.notna(v)}
    if not valid:
        return "N/A"

    high_count = sum(1 for v in valid.values() if v >= PCT_DRIVER_HIGH)
    if high_count >= 3:
        return "BROAD_STRESS"
    if high_count == 0:
        return "NO_STRESS"
    top = max(valid, key=valid.get)
    return f"{top}_DRIVEN"


# ────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ────────────────────────────────────────────────────────────────────────────

def process_gfcm_logic(
    df_raw: pd.DataFrame, window: int = ROLLING_WINDOW
) -> tuple[pd.DataFrame, dict]:
    """
    Full pipeline: z-score → percentile → PCA → regime/driver.

    Returns
    -------
    df_out : pd.DataFrame với OUTPUT_COLUMNS
    meta   : dict từ fit_static_pca (loadings, explained variance, interpretation)
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {}

    df = df_raw[RAW_COLUMNS].copy()

    df["Credit_Quality_Spread"] = df["CCC_OAS"] - df["HY_OAS"]

    df["VIX_z"] = _rolling_zscore(df["VIX"], window)
    df["MOVE_z"] = _rolling_zscore(df["MOVE"], window)
    df["HY_z"] = _rolling_zscore(df["HY_OAS"], window)
    df["CCC_z"] = _rolling_zscore(df["CCC_OAS"], window)

    df["VIX_pct"] = _rolling_pct_rank(df["VIX"], window)
    df["MOVE_pct"] = _rolling_pct_rank(df["MOVE"], window)
    df["HY_pct"] = _rolling_pct_rank(df["HY_OAS"], window)
    df["CCC_pct"] = _rolling_pct_rank(df["CCC_OAS"], window)
    df["CQS_pct"] = _rolling_pct_rank(df["Credit_Quality_Spread"], window)

    df_pc, meta = fit_static_pca(df[["VIX_z", "MOVE_z", "HY_z", "CCC_z"]])
    df["PC1"] = df_pc["PC1"]
    df["PC2"] = df_pc["PC2"]

    df["PC1_pct"] = _rolling_pct_rank(df["PC1"], window)

    df["Regime"] = [_classify_regime(p) for p in df["PC1_pct"]]
    df["Driver"] = [
        _classify_driver(v, m, h, c)
        for v, m, h, c in zip(df["VIX_pct"], df["MOVE_pct"], df["HY_pct"], df["CCC_pct"])
    ]

    df = df.replace([np.inf, -np.inf], np.nan)
    return df[OUTPUT_COLUMNS], meta


def summarize_latest(df_processed: pd.DataFrame) -> dict:
    """
    Snapshot dòng cuối có PCA hợp lệ (đủ window) cho UI/AI.
    """
    empty = {
        "date": "", "vix": 0.0, "move": 0.0, "hy_oas": 0.0, "ccc_oas": 0.0,
        "credit_quality_spread": 0.0,
        "vix_pct": 0.0, "move_pct": 0.0, "hy_pct": 0.0, "ccc_pct": 0.0,
        "cqs_pct": 0.0,
        "vix_z": 0.0, "move_z": 0.0, "hy_z": 0.0, "ccc_z": 0.0,
        "pc1": 0.0, "pc2": 0.0, "pc1_pct": 0.0,
        "regime": "N/A", "driver": "N/A",
        "pc1_5d_change": 0.0,
    }
    if df_processed is None or df_processed.empty:
        return empty

    df_clean = df_processed.dropna(subset=["PC1_pct"])
    if df_clean.empty:
        return empty

    latest = df_clean.iloc[-1]
    pc1_series = df_clean["PC1"].dropna()
    if len(pc1_series) >= 6:
        pc1_5d = float(pc1_series.iloc[-1] - pc1_series.iloc[-6])
    else:
        pc1_5d = 0.0

    def _f(v: Optional[float]) -> float:
        return float(v) if pd.notna(v) else 0.0

    return {
        "date": df_clean.index[-1].strftime("%Y-%m-%d"),
        "vix": _f(latest["VIX"]),
        "move": _f(latest["MOVE"]),
        "hy_oas": _f(latest["HY_OAS"]),
        "ccc_oas": _f(latest["CCC_OAS"]),
        "credit_quality_spread": _f(latest["Credit_Quality_Spread"]),
        "vix_pct": _f(latest["VIX_pct"]),
        "move_pct": _f(latest["MOVE_pct"]),
        "hy_pct": _f(latest["HY_pct"]),
        "ccc_pct": _f(latest["CCC_pct"]),
        "cqs_pct": _f(latest["CQS_pct"]),
        "vix_z": _f(latest["VIX_z"]),
        "move_z": _f(latest["MOVE_z"]),
        "hy_z": _f(latest["HY_z"]),
        "ccc_z": _f(latest["CCC_z"]),
        "pc1": _f(latest["PC1"]),
        "pc2": _f(latest["PC2"]),
        "pc1_pct": _f(latest["PC1_pct"]),
        "regime": str(latest["Regime"]),
        "driver": str(latest["Driver"]),
        "pc1_5d_change": pc1_5d,
    }
