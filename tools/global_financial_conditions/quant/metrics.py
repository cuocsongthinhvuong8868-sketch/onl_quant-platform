"""
tools/global_financial_conditions/quant/metrics.py
Core logic cho Global Financial Conditions Monitor (GFCM).

11 indicators (3 nhóm):

  VOLATILITY (5):
    - VIX       : FRED VIXCLS              — CBOE equity vol (S&P 500 30d implied)
    - MOVE      : Yahoo ^MOVE              — ICE BofAML US bond vol estimate
    - SKEW      : Yahoo ^SKEW              — CBOE tail risk premium (left-tail fear)
    - OVX       : Yahoo ^OVX               — CBOE crude oil ETF vol
    - VVIX      : Yahoo ^VVIX              — CBOE vol-of-vol (VIX of VIX)

  CREDIT (4):
    - HY OAS    : FRED BAMLH0A0HYM2        — ICE BofA US HY broad OAS
    - CCC OAS   : FRED BAMLH0A3HYC         — ICE BofA CCC & Lower US HY OAS
    - IG OAS    : FRED BAMLC0A0CM          — ICE BofA US Investment Grade Corp OAS
    - EM OAS    : FRED BAMLEMCBPIOAS       — ICE BofA EM Corp Plus OAS

  MACRO (2):
    - 2s10s     : FRED T10Y2Y              — 10Y minus 2Y Treasury yield (recession proxy)
    - DXY       : Yahoo DX-Y.NYB           — ICE US Dollar Index

  Derived:
    - Credit_Quality_Spread = CCC − HY

PCA composite chỉ dùng 6 series core: VIX, MOVE, SKEW, HY_OAS, CCC_OAS, IG_OAS.
EM_OAS, OVX, VVIX, T10Y2Y, DXY là auxiliary — chỉ z-score + percentile, KHÔNG vào PCA.

Pipeline:
  1. fetch_raw_data(fred_api_key) -> DataFrame 11 raw cols
  2. process_gfcm_logic(df_raw) -> DataFrame với:
       * Per-series rolling z-score & percentile rank 252d (1Y)
       * Credit Quality Spread (CCC − HY) + percentile
       * Static PCA 6-series (PC1 = stress, PC2 = divergence)
       * PC1 rolling percentile 1Y
       * Regime classification (STRESS / ELEVATED / CALM)
       * Driver flag (EQUITY / RATES / SKEW / HY_CREDIT / CCC_CREDIT / IG_CREDIT / BROAD_STRESS / NO_STRESS)

Quant layer KHÔNG import Streamlit. Errors RAISE thay vì swallow.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ── FRED series ──
FRED_SERIES = {
    "VIX": "VIXCLS",                  # CBOE Volatility Index
    "HY_OAS": "BAMLH0A0HYM2",         # ICE BofA US HY Index OAS (broad)
    "CCC_OAS": "BAMLH0A3HYC",         # ICE BofA CCC & Lower US HY OAS
    "IG_OAS": "BAMLC0A0CM",           # ICE BofA US Corp Index (Investment Grade) OAS
    "EM_OAS": "BAMLEMCBPIOAS",        # ICE BofA EM Corp Plus Index OAS
    "T10Y2Y": "T10Y2Y",               # 10Y − 2Y Treasury (yield curve)
}

# ── Yahoo tickers ──
YAHOO_TICKERS = {
    "MOVE": "^MOVE",                  # ICE BofAML Bond Volatility
    "SKEW": "^SKEW",                  # CBOE SKEW (tail risk)
    "OVX": "^OVX",                    # CBOE Oil VIX
    "VVIX": "^VVIX",                  # CBOE VIX-of-VIX
    "DXY": "DX-Y.NYB",                # ICE US Dollar Index
}

START_DATE = "2003-01-01"       # MOVE Yahoo coverage starts ~2003
ROLLING_WINDOW = 252            # 1 năm trading days — FRED ICE BofA chỉ cấp ~3 năm history
                                # (ICE pull license 2021); 252d cho phép ~280 valid regime points.

PCT_STRESS = 0.80               # PC1_pct ≥ 0.80 → STRESS
PCT_ELEVATED = 0.50             # 0.50 ≤ PC1_pct < 0.80 → ELEVATED, dưới = CALM
PCT_DRIVER_HIGH = 0.80          # Driver flag threshold per-series

# Raw columns (theo thứ tự fetch + merge)
RAW_COLUMNS = [
    # Volatility
    "VIX", "MOVE", "SKEW", "OVX", "VVIX",
    # Credit
    "HY_OAS", "CCC_OAS", "IG_OAS", "EM_OAS",
    # Macro
    "T10Y2Y", "DXY",
]

# Cột vào PCA composite (6 core)
PCA_COLUMNS = ["VIX", "MOVE", "SKEW", "HY_OAS", "CCC_OAS", "IG_OAS"]

# Cột auxiliary (không vào PCA, chỉ z + pct)
AUX_COLUMNS = ["OVX", "VVIX", "EM_OAS", "T10Y2Y", "DXY"]

# Mapping series → short label dùng cho z/pct suffix
_LABEL = {
    "VIX": "VIX",
    "MOVE": "MOVE",
    "SKEW": "SKEW",
    "OVX": "OVX",
    "VVIX": "VVIX",
    "HY_OAS": "HY",
    "CCC_OAS": "CCC",
    "IG_OAS": "IG",
    "EM_OAS": "EM",
    "T10Y2Y": "T10Y2Y",
    "DXY": "DXY",
}

# Generate full OUTPUT_COLUMNS
_z_cols = [f"{_LABEL[c]}_z" for c in RAW_COLUMNS]
_pct_cols = [f"{_LABEL[c]}_pct" for c in RAW_COLUMNS]

OUTPUT_COLUMNS = (
    RAW_COLUMNS
    + ["Credit_Quality_Spread"]
    + _z_cols
    + _pct_cols
    + ["CQS_pct"]
    + ["PC1", "PC2", "PC1_pct"]
    + ["Regime", "Driver"]
)


# ────────────────────────────────────────────────────────────────────────────
# Fetchers
# ────────────────────────────────────────────────────────────────────────────

def fetch_fred_series(api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Pull các FRED series cấu hình trong FRED_SERIES.

    Returns
    -------
    pd.DataFrame index=Date (datetime), columns=list(FRED_SERIES.keys()).
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
        n_valid = int(s.dropna().shape[0])
        if n_valid == 0:
            raise RuntimeError(
                f"FRED series '{code}' (mapped to {col}) trả về 0 quan sát kể từ "
                f"{start_date}. Series có thể đã bị ICE BofA pull khỏi FRED (2021) "
                f"hoặc ID đã đổi. Verify tại https://fred.stlouisfed.org/series/{code}"
            )
        cols[col] = s

    df = pd.DataFrame(cols).sort_index()
    df.index.name = "DATE"
    return df


def fetch_yahoo_series(start_date: str = START_DATE) -> pd.DataFrame:
    """
    Pull các Yahoo tickers cấu hình trong YAHOO_TICKERS qua yfinance batch download.

    Returns
    -------
    pd.DataFrame index=Date (datetime), columns=list(YAHOO_TICKERS.keys()).
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện 'yfinance'. Cài đặt: pip install yfinance"
        ) from e

    out = {}
    for col, ticker in YAHOO_TICKERS.items():
        try:
            df_yf = yf.download(
                ticker,
                start=start_date,
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            raise RuntimeError(f"Lỗi khi tải {ticker} từ Yahoo Finance: {e}") from e

        if df_yf is None or df_yf.empty:
            raise RuntimeError(
                f"Yahoo Finance trả về dữ liệu rỗng cho ticker '{ticker}' "
                f"(mapped to {col}). Có thể ticker tạm bị rate-limit, đã đổi, "
                f"hoặc network lỗi — thử lại sau."
            )

        if isinstance(df_yf.columns, pd.MultiIndex):
            df_yf.columns = df_yf.columns.get_level_values(0)

        if "Close" not in df_yf.columns:
            raise RuntimeError(
                f"Yahoo response cho '{ticker}' thiếu cột 'Close'. Có: {list(df_yf.columns)}"
            )

        s = df_yf["Close"].astype(float)
        s.index = pd.to_datetime(s.index)
        s.name = col
        out[col] = s

    df = pd.DataFrame(out).sort_index()
    df.index.name = "DATE"
    return df


def fetch_raw_data(fred_api_key: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    Merge FRED (6 series) + Yahoo (5 series) → 1 DataFrame 11 cột.
    Outer-join (giữ tất cả ngày), forward-fill từng cột tới 5 phiên để
    bù holiday lệch giữa US equity / bond / FX market. Dropna ở processing.
    """
    df_fred = fetch_fred_series(fred_api_key, start_date=start_date)
    df_yahoo = fetch_yahoo_series(start_date=start_date)

    df = df_fred.join(df_yahoo, how="outer").sort_index()
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
    Fit PCA 1 lần trên toàn bộ z-score history 6 cột PCA core → project mọi ngày.

    Sign convention: force PC1 loading trên VIX_z dương → PC1 cao = stress.
    PC2 sign convention: force loading trên HY_z dương → PC2 cao = credit-tilt.

    Parameters
    ----------
    df_z : pd.DataFrame
        Columns [VIX_z, MOVE_z, SKEW_z, HY_z, CCC_z, IG_z].

    Returns
    -------
    df_pc : pd.DataFrame [PC1, PC2] aligned tới input index.
    meta  : dict {
        "loadings": pd.DataFrame (rows=6 series, cols=[PC1, PC2]),
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

    z_cols = [f"{_LABEL[c]}_z" for c in PCA_COLUMNS]
    df_clean = df_z[z_cols].dropna()

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
    vol_avg = (pc2_load["VIX_z"] + pc2_load["MOVE_z"] + pc2_load["SKEW_z"]) / 3
    credit_avg = (pc2_load["HY_z"] + pc2_load["CCC_z"] + pc2_load["IG_z"]) / 3
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
    vix_pct: float, move_pct: float, skew_pct: float,
    hy_pct: float, ccc_pct: float, ig_pct: float,
) -> str:
    """
    Driver dựa trên 6 PCA series.

    BROAD_STRESS: ≥ 4/6 ≥ 80 percentile.
    NO_STRESS: 0/6 ≥ 80.
    Còn lại: argmax → {EQUITY|RATES|SKEW|HY_CREDIT|CCC_CREDIT|IG_CREDIT}_DRIVEN.
    """
    pcts = {
        "EQUITY": vix_pct,
        "RATES": move_pct,
        "SKEW": skew_pct,
        "HY_CREDIT": hy_pct,
        "CCC_CREDIT": ccc_pct,
        "IG_CREDIT": ig_pct,
    }
    valid = {k: v for k, v in pcts.items() if pd.notna(v)}
    if not valid:
        return "N/A"

    high_count = sum(1 for v in valid.values() if v >= PCT_DRIVER_HIGH)
    if high_count >= 4:
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
    Full pipeline: z-score → percentile → PCA (6 core) → regime/driver.
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {}

    df = df_raw[RAW_COLUMNS].copy()

    df["Credit_Quality_Spread"] = df["CCC_OAS"] - df["HY_OAS"]

    for col in RAW_COLUMNS:
        label = _LABEL[col]
        df[f"{label}_z"] = _rolling_zscore(df[col], window)
        df[f"{label}_pct"] = _rolling_pct_rank(df[col], window)

    df["CQS_pct"] = _rolling_pct_rank(df["Credit_Quality_Spread"], window)

    pca_z_cols = [f"{_LABEL[c]}_z" for c in PCA_COLUMNS]
    df_pc, meta = fit_static_pca(df[pca_z_cols])
    df["PC1"] = df_pc["PC1"]
    df["PC2"] = df_pc["PC2"]

    df["PC1_pct"] = _rolling_pct_rank(df["PC1"], window)

    df["Regime"] = [_classify_regime(p) for p in df["PC1_pct"]]
    df["Driver"] = [
        _classify_driver(v, m, s, h, c, i)
        for v, m, s, h, c, i in zip(
            df["VIX_pct"], df["MOVE_pct"], df["SKEW_pct"],
            df["HY_pct"], df["CCC_pct"], df["IG_pct"],
        )
    ]

    df = df.replace([np.inf, -np.inf], np.nan)
    return df[OUTPUT_COLUMNS], meta


def summarize_latest(df_processed: pd.DataFrame) -> dict:
    """
    Snapshot dòng cuối có PCA hợp lệ (đủ window) cho UI/AI.
    """
    raw_keys = [c.lower() for c in RAW_COLUMNS]
    z_keys = [f"{_LABEL[c].lower()}_z" for c in RAW_COLUMNS]
    pct_keys = [f"{_LABEL[c].lower()}_pct" for c in RAW_COLUMNS]

    empty = {k: 0.0 for k in raw_keys + z_keys + pct_keys}
    empty.update({
        "date": "",
        "credit_quality_spread": 0.0,
        "cqs_pct": 0.0,
        "pc1": 0.0, "pc2": 0.0, "pc1_pct": 0.0,
        "regime": "N/A", "driver": "N/A",
        "pc1_5d_change": 0.0,
    })
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

    out = {
        "date": df_clean.index[-1].strftime("%Y-%m-%d"),
        "credit_quality_spread": _f(latest["Credit_Quality_Spread"]),
        "cqs_pct": _f(latest["CQS_pct"]),
        "pc1": _f(latest["PC1"]),
        "pc2": _f(latest["PC2"]),
        "pc1_pct": _f(latest["PC1_pct"]),
        "regime": str(latest["Regime"]),
        "driver": str(latest["Driver"]),
        "pc1_5d_change": pc1_5d,
    }
    for col in RAW_COLUMNS:
        label = _LABEL[col]
        out[col.lower()] = _f(latest[col])
        out[f"{label.lower()}_z"] = _f(latest[f"{label}_z"])
        out[f"{label.lower()}_pct"] = _f(latest[f"{label}_pct"])
    return out
