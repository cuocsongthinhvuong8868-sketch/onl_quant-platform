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
       * Per-series rolling z-score 252d (1Y)
       * Per-series percentile rank max 756d (3Y) with 252d warm-up
       * Credit Quality Spread (CCC − HY) + percentile rank max 756d
       * Expanding point-in-time PCA 6-series (PC1 = stress, PC2 = divergence)
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
ROLLING_WINDOW = 252            # Legacy default: 1Y z-score/PCA/regime window.
ZSCORE_WINDOW = ROLLING_WINDOW
PC1_PERCENTILE_WINDOW = ROLLING_WINDOW
SERIES_PERCENTILE_WINDOW = 756  # 3Y max trading-day window for indicator percentile ranks.
SERIES_PERCENTILE_MIN_PERIODS = ROLLING_WINDOW  # Start PR after 1Y to avoid empty credit history.

PCT_STRESS = 0.80               # PC1_pct ≥ 0.80 → STRESS
PCT_ELEVATED = 0.50             # 0.50 ≤ PC1_pct < 0.80 → ELEVATED, dưới = CALM
PCT_DRIVER_HIGH = 0.80          # Driver flag threshold per-series

# PC1 smoothing — EMA span=5 (half-life ~3 ngày, lag ~3 ngày).
# Áp dụng để giảm regime flicker; raw PC1 vẫn được lưu để tính 5d change.
PC1_EMA_SPAN = 5

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
    + ["PC1", "PC1_smooth", "PC2", "PC1_pct"]
    + ["Regime", "Driver"]
)


def load_cached_gfcm(path, recompute_analytics: bool = True) -> pd.DataFrame:
    """
    Read a saved GFCM cache and normalize DATE defensively.

    CSV cache files can be edited or merged outside the updater. If conflict
    markers or other invalid rows enter the file, pandas may leave DATE as
    strings even with parse_dates, which later breaks .strftime() callers.

    Mặc định analytics được tính lại từ raw columns để cache cũ từng tạo bằng
    full-history static PCA không tiếp tục rò rỉ vào UI/AI sau khi code đổi sang
    point-in-time PCA.
    """
    df = pd.read_csv(path)
    if "DATE" not in df.columns:
        raise ValueError(f"GFCM cache is missing required DATE column: {path}")

    parsed_dates = pd.to_datetime(df["DATE"], errors="coerce")
    df = df.loc[parsed_dates.notna()].copy()
    df["DATE"] = parsed_dates.loc[parsed_dates.notna()]

    df = (
        df.sort_values("DATE", kind="mergesort")
        .drop_duplicates(subset=["DATE"], keep="last")
        .set_index("DATE")
        .sort_index()
    )

    numeric_cols = [c for c in OUTPUT_COLUMNS if c not in ("Regime", "Driver")]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if recompute_analytics:
        missing_raw = [column for column in RAW_COLUMNS if column not in df.columns]
        if missing_raw:
            raise ValueError(f"GFCM cache thiếu raw columns để recompute: {missing_raw}")
        df, _ = process_gfcm_logic(df[RAW_COLUMNS])
    return df


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


def _rolling_pct_rank(
    s: pd.Series, window: int, min_periods: int | None = None
) -> pd.Series:
    if min_periods is None:
        min_periods = window
    return s.rolling(window=window, min_periods=min_periods).rank(pct=True)


# ────────────────────────────────────────────────────────────────────────────
# PCA
# ────────────────────────────────────────────────────────────────────────────

def fit_expanding_pca(
    df_z: pd.DataFrame,
    min_pca_samples: int = 60,
    refit_every: int = 21,
) -> tuple[pd.DataFrame, dict]:
    """
    Expanding point-in-time PCA trên 6 z-score core.

    Tại refit point t, model chỉ fit trên [0, t), rồi project tối đa
    ``refit_every`` phiên kế tiếp. Vì vậy append dữ liệu tương lai không làm
    revision PC1/PC2 lịch sử.

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
        "n_samples_fit": int (latest refit),
        "pca_method": "expanding_point_in_time",
        "refit_every": int,
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

    if min_pca_samples < 2:
        raise ValueError("min_pca_samples phải >= 2")
    if refit_every < 1:
        raise ValueError("refit_every phải >= 1")

    if len(df_clean) < min_pca_samples:
        return (
            pd.DataFrame(index=df_z.index, columns=["PC1", "PC2"], dtype=float),
            {
                "loadings": None,
                "explained_variance_ratio": [],
                "n_samples_fit": len(df_clean),
                "pca_method": "expanding_point_in_time",
                "refit_every": refit_every,
                "pc1_interpretation": "Insufficient data",
                "pc2_interpretation": "Insufficient data",
            },
        )

    vix_idx = z_cols.index("VIX_z")
    hy_idx = z_cols.index("HY_z")
    df_pc_clean = pd.DataFrame(
        np.nan,
        index=df_clean.index,
        columns=["PC1", "PC2"],
        dtype=float,
    )
    latest_components = None
    latest_evr: list[float] = []
    latest_train_size = 0

    for start in range(min_pca_samples, len(df_clean), refit_every):
        train = df_clean.iloc[:start]
        end = min(start + refit_every, len(df_clean))
        prediction = df_clean.iloc[start:end]

        pca = PCA(n_components=2)
        pca.fit(train.values)
        components = pca.components_.copy()
        signs = np.ones(2, dtype=float)
        if components[0, vix_idx] < 0:
            signs[0] = -1.0
            components[0] *= -1
        if components[1, hy_idx] < 0:
            signs[1] = -1.0
            components[1] *= -1

        projected = pca.transform(prediction.values) * signs
        df_pc_clean.iloc[start:end] = projected
        latest_components = components
        latest_evr = pca.explained_variance_ratio_.tolist()
        latest_train_size = len(train)

    df_pc = df_pc_clean.reindex(df_z.index)
    loadings_df = None
    if latest_components is not None:
        loadings_df = pd.DataFrame(
            latest_components.T,
            index=z_cols,
            columns=["PC1", "PC2"],
        )

    if loadings_df is None:
        pc2_interp = "Insufficient data"
    else:
        pc2_load = loadings_df["PC2"]
        vol_avg = (pc2_load["VIX_z"] + pc2_load["MOVE_z"] + pc2_load["SKEW_z"]) / 3
        credit_avg = (pc2_load["HY_z"] + pc2_load["CCC_z"] + pc2_load["IG_z"]) / 3
        if credit_avg > vol_avg:
            pc2_interp = "PC2 cao = credit-driven; PC2 thấp = vol-driven"
        else:
            pc2_interp = "PC2 cao = vol-driven; PC2 thấp = credit-driven"

    meta = {
        "loadings": loadings_df,
        "explained_variance_ratio": latest_evr,
        "n_samples_fit": latest_train_size,
        "pca_method": "expanding_point_in_time",
        "refit_every": refit_every,
        "first_prediction_date": (
            str(df_clean.index[min_pca_samples])
            if len(df_clean) > min_pca_samples
            else None
        ),
        "pc1_interpretation": "PC1 cao = financial conditions tighten (stress)",
        "pc2_interpretation": pc2_interp,
    }
    return df_pc, meta


def fit_static_pca(df_z: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Backward-compatible alias; implementation is now point-in-time."""
    return fit_expanding_pca(df_z)


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
    df_raw: pd.DataFrame,
    window: int = ZSCORE_WINDOW,
    *,
    pct_window: int = SERIES_PERCENTILE_WINDOW,
    pct_min_periods: int = SERIES_PERCENTILE_MIN_PERIODS,
    pc1_pct_window: int = PC1_PERCENTILE_WINDOW,
) -> tuple[pd.DataFrame, dict]:
    """
    Full pipeline: z-score → percentile → PCA (6 core) → regime/driver.

    `window` remains the 1Y z-score/PCA window. Per-indicator percentile ranks
    use a 3Y max window with a 1Y warm-up; PC1_pct/regime stays 1Y so the
    shorter post-2023 ICE BofA credit history does not blank out PCA/regime.
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {}

    df = df_raw[RAW_COLUMNS].copy()

    df["Credit_Quality_Spread"] = df["CCC_OAS"] - df["HY_OAS"]

    for col in RAW_COLUMNS:
        label = _LABEL[col]
        df[f"{label}_z"] = _rolling_zscore(df[col], window)
        df[f"{label}_pct"] = _rolling_pct_rank(
            df[col], pct_window, min_periods=pct_min_periods
        )

    df["CQS_pct"] = _rolling_pct_rank(
        df["Credit_Quality_Spread"], pct_window, min_periods=pct_min_periods
    )

    pca_z_cols = [f"{_LABEL[c]}_z" for c in PCA_COLUMNS]
    df_pc, meta = fit_expanding_pca(df[pca_z_cols])
    df["PC1"] = df_pc["PC1"]
    df["PC2"] = df_pc["PC2"]

    # EMA smoothing PC1 để giảm regime flicker (span=5, half-life ~3 ngày).
    # Regime + PC1_pct dùng PC1_smooth; PC1 raw giữ nguyên cho 5d change.
    df["PC1_smooth"] = df["PC1"].ewm(span=PC1_EMA_SPAN, adjust=False).mean()
    df["PC1_pct"] = _rolling_pct_rank(df["PC1_smooth"], pc1_pct_window)
    meta.update({
        "zscore_window": window,
        "series_percentile_window": pct_window,
        "series_percentile_min_periods": pct_min_periods,
        "pc1_percentile_window": pc1_pct_window,
    })

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
        "pc1": 0.0, "pc1_smooth": 0.0, "pc2": 0.0, "pc1_pct": 0.0,
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

    latest_date = pd.to_datetime(df_clean.index[-1], errors="coerce")
    latest_date_str = (
        str(df_clean.index[-1])
        if pd.isna(latest_date)
        else latest_date.strftime("%Y-%m-%d")
    )

    out = {
        "date": latest_date_str,
        "credit_quality_spread": _f(latest["Credit_Quality_Spread"]),
        "cqs_pct": _f(latest["CQS_pct"]),
        "pc1": _f(latest["PC1"]),
        "pc1_smooth": _f(latest["PC1_smooth"]),
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
