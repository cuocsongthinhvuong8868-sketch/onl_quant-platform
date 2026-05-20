"""
factors.py — Compute 10 cross-sectional factor exposures cho universe VN.

Tất cả factor sign-oriented "higher = better" theo academic prior:
- Mom 12-1 / Mom 6-1: positive return → +
- ST Reversal: -return 21d → +
- LT Reversal: -return từ t-1260 → t-756 → +
- LowVol 252d: -σ(return) → +
- Beta 60d: -β(stock, VN-Index) → +
- IdioVol 60d: -σ(residual) → +
- Liquidity (Amihud): -mean(|r| / dollar_volume) → +
- Size proxy: log(median ADV20d) → +
- MAX 21d: -max(daily return) → + (anti-lottery)
- Skewness 60d: -skew(return) → + (negative skew preference)

Quant layer KHÔNG import Streamlit. Errors RAISE — UI mới catch.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Window constants ──────────────────────────────────────────
WINDOW_MOM_LONG = 252
WINDOW_MOM_MID = 126
WINDOW_MOM_SKIP = 21
WINDOW_ST_REV = 21
WINDOW_LT_REV_START = 1260
WINDOW_LT_REV_END = 756
WINDOW_VOL = 252
WINDOW_BETA = 60
WINDOW_LIQ = 60
WINDOW_SIZE = 20
WINDOW_MAX = 21
WINDOW_SKEW = 60

# Minimum bars required cho universe candidate. Mặc định 5Y + buffer cho LT reversal.
MIN_BARS_FULL = WINDOW_LT_REV_START + WINDOW_MOM_SKIP + 5

# Factor names ordering — dùng nhất quán xuyên suốt pipeline
FACTOR_NAMES = [
    "Mom_12_1",
    "Mom_6_1",
    "ST_Reversal",
    "LT_Reversal",
    "LowVol",
    "Beta_Low",
    "IdioVol_Low",
    "Liquidity",
    "Size",
    "Anti_Lottery",  # composite -MAX -skew (gộp lottery factor)
]


# ── Helpers ───────────────────────────────────────────────────
def _safe_pct_change(df: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return df.pct_change(fill_method=None)


def _last_close(prices: pd.DataFrame, offset: int) -> pd.Series:
    """Lấy giá đóng cửa tại index offset từ cuối (offset=0 là latest)."""
    if offset >= len(prices):
        return pd.Series(np.nan, index=prices.columns)
    return prices.iloc[-offset - 1]


# ── Individual factor functions ───────────────────────────────
def momentum_12_1(prices: pd.DataFrame) -> pd.Series:
    """12M return skip most recent 21d (avoid ST reversal contamination)."""
    if len(prices) < WINDOW_MOM_LONG + WINDOW_MOM_SKIP + 1:
        return pd.Series(np.nan, index=prices.columns)
    p_recent = prices.iloc[-WINDOW_MOM_SKIP - 1]
    p_old = prices.iloc[-WINDOW_MOM_LONG - 1]
    return (p_recent / p_old - 1.0)


def momentum_6_1(prices: pd.DataFrame) -> pd.Series:
    if len(prices) < WINDOW_MOM_MID + WINDOW_MOM_SKIP + 1:
        return pd.Series(np.nan, index=prices.columns)
    p_recent = prices.iloc[-WINDOW_MOM_SKIP - 1]
    p_old = prices.iloc[-WINDOW_MOM_MID - 1]
    return (p_recent / p_old - 1.0)


def st_reversal(prices: pd.DataFrame) -> pd.Series:
    """Short-term reversal: -return 21d. Higher = lower recent return = better."""
    if len(prices) < WINDOW_ST_REV + 1:
        return pd.Series(np.nan, index=prices.columns)
    r_21 = prices.iloc[-1] / prices.iloc[-WINDOW_ST_REV - 1] - 1.0
    return -r_21


def lt_reversal(prices: pd.DataFrame) -> pd.Series:
    """LT reversal 5Y → 3Y window. Higher = lower distant return = better."""
    if len(prices) < WINDOW_LT_REV_START + 1:
        return pd.Series(np.nan, index=prices.columns)
    p_5y = prices.iloc[-WINDOW_LT_REV_START - 1]
    p_3y = prices.iloc[-WINDOW_LT_REV_END - 1]
    return -(p_3y / p_5y - 1.0)


def low_vol(prices: pd.DataFrame) -> pd.Series:
    """-σ(daily return) on 252d window."""
    if len(prices) < WINDOW_VOL + 2:
        return pd.Series(np.nan, index=prices.columns)
    rets = _safe_pct_change(prices).iloc[-WINDOW_VOL:]
    return -rets.std()


def beta_idiovol(prices: pd.DataFrame, market: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Compute beta vs market AND idiosyncratic vol cùng lúc (chia sẻ regression).

    Trả về (-beta, -idio_sigma) — cả 2 đã sign-oriented.
    """
    if len(prices) < WINDOW_BETA + 2:
        nan_ser = pd.Series(np.nan, index=prices.columns)
        return nan_ser, nan_ser

    rets = _safe_pct_change(prices).iloc[-WINDOW_BETA:]
    mkt = _safe_pct_change(market).reindex(rets.index)

    # Align: drop rows where mkt is NaN
    valid = mkt.dropna()
    rets = rets.loc[valid.index]
    mkt = valid

    mu_m = float(mkt.mean())
    var_m = float(mkt.var())
    if var_m <= 0:
        nan_ser = pd.Series(np.nan, index=prices.columns)
        return nan_ser, nan_ser

    # OLS regression per stock: r_t = α + β * m_t + ε_t
    mkt_demean = mkt - mu_m
    rets_demean = rets.sub(rets.mean(axis=0), axis=1)
    cov_rm = rets_demean.mul(mkt_demean, axis=0).mean()
    beta = cov_rm / var_m

    # Residual: r - (α + β * m); α implicit qua mean centering
    pred = pd.DataFrame(
        np.outer(mkt_demean.values, beta.values),
        index=rets.index, columns=rets.columns,
    )
    resid = rets_demean - pred
    idio_sigma = resid.std()

    return -beta, -idio_sigma


def liquidity_amihud(prices: pd.DataFrame, volumes: pd.DataFrame) -> pd.Series:
    """-Amihud illiquidity = -mean(|r| / dollar_volume) trên 60d.

    Higher value = lower Amihud = more liquid = better.
    """
    if len(prices) < WINDOW_LIQ + 2:
        return pd.Series(np.nan, index=prices.columns)

    rets = _safe_pct_change(prices).iloc[-WINDOW_LIQ:]
    dollar_vol = (prices * volumes).iloc[-WINDOW_LIQ:].replace(0, np.nan)
    # Align columns
    common = rets.columns.intersection(dollar_vol.columns)
    rets = rets[common]
    dollar_vol = dollar_vol[common]

    illiq = (rets.abs() / dollar_vol).mean()
    # Một số mã có dollar_vol = 0 toàn bộ → mean = NaN
    return -illiq


def size_adv(prices: pd.DataFrame, volumes: pd.DataFrame) -> pd.Series:
    """Size proxy = log(median dollar volume 20d). Higher = lớn hơn = better."""
    if len(prices) < WINDOW_SIZE + 1:
        return pd.Series(np.nan, index=prices.columns)
    dollar_vol = (prices * volumes).iloc[-WINDOW_SIZE:]
    median_dv = dollar_vol.median()
    # log(1 + x) tránh log(0)
    return np.log1p(median_dv)


def anti_lottery(prices: pd.DataFrame) -> pd.Series:
    """Composite anti-lottery factor = -MAX21d - skew60d.

    MAX (Bali-Cakici-Whitelaw 2011): high MAX = lottery preference → bad
    Skew positive: positive-skew stocks attract retail → underperform
    """
    if len(prices) < max(WINDOW_MAX, WINDOW_SKEW) + 2:
        return pd.Series(np.nan, index=prices.columns)

    rets = _safe_pct_change(prices)
    max_21 = rets.iloc[-WINDOW_MAX:].max()
    skew_60 = rets.iloc[-WINDOW_SKEW:].skew()

    # Convert both to comparable scale via standardize internally
    # (sẽ xs-z lại ở scoring layer, nên không cần ở đây — chỉ cần composite)
    return -(max_21 + 0.01 * skew_60)  # weight nhỏ cho skew để không dominate max


# ── Master compute ────────────────────────────────────────────
def compute_all_factors(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    market: pd.Series,
) -> pd.DataFrame:
    """Compute 10 factor exposures (raw, sign-oriented) cho universe.

    Parameters
    ----------
    prices : DataFrame index=date, columns=ticker. Close adjusted.
    volumes : DataFrame same shape, shares traded.
    market : Series index=date, VN-Index close.

    Returns
    -------
    DataFrame index=ticker, columns=FACTOR_NAMES. Raw values (chưa z-score).
    Mã không đủ bars → NaN cho factor đó.
    """
    if prices.empty:
        raise ValueError("prices empty")
    if not prices.columns.equals(volumes.columns):
        common = prices.columns.intersection(volumes.columns)
        prices = prices[common]
        volumes = volumes[common]

    beta_neg, idio_neg = beta_idiovol(prices, market)

    factors = pd.DataFrame({
        "Mom_12_1": momentum_12_1(prices),
        "Mom_6_1": momentum_6_1(prices),
        "ST_Reversal": st_reversal(prices),
        "LT_Reversal": lt_reversal(prices),
        "LowVol": low_vol(prices),
        "Beta_Low": beta_neg,
        "IdioVol_Low": idio_neg,
        "Liquidity": liquidity_amihud(prices, volumes),
        "Size": size_adv(prices, volumes),
        "Anti_Lottery": anti_lottery(prices),
    })

    # Reorder columns theo FACTOR_NAMES (đảm bảo deterministic)
    factors = factors[FACTOR_NAMES]
    return factors
