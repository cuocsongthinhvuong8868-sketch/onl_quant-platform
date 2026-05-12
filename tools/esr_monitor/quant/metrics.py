"""
ESR Monitor — Quant layer
==========================
Port from Desktop/9999/ESR monitor/ESR.app.py
5-pillar Systemic Stress Index (SSI) for VN30 with look-ahead-free aggregation.

PILLARS (all oriented so HIGHER = HIGHER stress):
    S_VOL  : Realized vol of index (20d rolling, annualized)
    S_PRES : Selling pressure (down-day volume share, 5d)
    S_COR  : Systemic correlation (rolling 60d PCA-1 explained variance)
    S_LIQ  : Illiquidity (cross-sectional median Amihud, 20d rolling)
    S_VAL  : Valuation tension = rolling 252d VN30 return - deposit rate

Downside variants: S_VOL_DOWN (semi-deviation), S_COR_DOWN (down-days only),
                   S_LIQ_DOWN (down-day Amihud)

AGGREGATION:
    Expanding-window PCA(1) on rank-transformed pillars, sign-aligned.
    Output SSI ∈ [0, 1] + EMA smoothing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

logger = logging.getLogger("ESR")

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
VN30_TICKERS: Tuple[str, ...] = (
    'ACB', 'BCM', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG',
    'MBB', 'MSN', 'MWG', 'PLX', 'POW', 'SAB', 'SHB', 'SSB', 'SSI', 'STB',
    'TCB', 'TPB', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VRE',
)

# ──────────────────────────────────────────────
# Pillar Engine
# ──────────────────────────────────────────────
class PillarEngine:
    """Computes 5 stress pillars. All oriented so HIGHER = MORE STRESS."""

    # ---- symmetric pillars ----

    @staticmethod
    def s_vol(idx_close: pd.Series, window: int = 20) -> pd.Series:
        """Annualized realized volatility."""
        ret = idx_close.pct_change()
        return ret.rolling(window).std() * np.sqrt(252)

    @staticmethod
    def s_pressure(idx_close: pd.Series, idx_volume: pd.Series, window: int = 5) -> pd.Series:
        """Down-day volume share. High = selling pressure."""
        ret = idx_close.pct_change()
        down_vol = (idx_volume * (ret < 0).astype(int)).rolling(window).sum()
        total_vol = idx_volume.rolling(window).sum()
        return (down_vol / total_vol).replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def s_correlation(stock_returns: pd.DataFrame, window: int = 60) -> pd.Series:
        """Rolling PCA-1 explained variance on constituent returns."""
        n = len(stock_returns)
        out = pd.Series(index=stock_returns.index, dtype=float)
        for i in range(window, n):
            chunk = stock_returns.iloc[i - window:i]
            chunk = chunk.dropna(axis=1, thresh=int(window * 0.9))
            if chunk.shape[1] < 5:
                continue
            chunk = chunk.fillna(chunk.median())
            try:
                pca = PCA(n_components=1)
                pca.fit(chunk.values)
                out.iloc[i] = pca.explained_variance_ratio_[0]
            except Exception:
                pass
        return out

    @staticmethod
    def s_liquidity(stocks_long: pd.DataFrame, window: int = 20) -> pd.Series:
        """
        Cross-sectional MEDIAN Amihud illiquidity, rolling smoothed.
        stocks_long must have columns: time, ticker, close, volume
        """
        df = stocks_long.copy()
        df['ret_abs'] = df.groupby('ticker')['close'].pct_change().abs()
        dollar_vol = (df['close'] * df['volume']).replace(0, np.nan)
        df['amihud'] = df['ret_abs'] / dollar_vol
        daily = df.groupby('time')['amihud'].median()
        return daily.rolling(window).mean()

    @staticmethod
    def s_valuation(idx_close: pd.Series, deposit_rate: float, window: int = 252) -> pd.Series:
        """S_VAL = rolling 1Y total return - risk-free deposit rate."""
        rolling_ret = idx_close.pct_change(window)
        return rolling_ret - deposit_rate

    # ---- downside-only variants ----

    @staticmethod
    def s_vol_down(idx_close: pd.Series, window: int = 20) -> pd.Series:
        """Downside semi-deviation, annualized (Sortino-style)."""
        ret = idx_close.pct_change()
        downside_sq = np.minimum(ret, 0.0) ** 2
        downside_var = downside_sq.rolling(window).mean()
        return np.sqrt(downside_var) * np.sqrt(252)

    @staticmethod
    def s_correlation_down(stock_returns: pd.DataFrame, idx_returns: pd.Series,
                           window: int = 60, min_down_days: int = 10) -> pd.Series:
        """Rolling PCA-1 EVR restricted to DOWN-MARKET days only."""
        n = len(stock_returns)
        out = pd.Series(index=stock_returns.index, dtype=float)
        idx_aligned = idx_returns.reindex(stock_returns.index)
        for i in range(window, n):
            chunk = stock_returns.iloc[i - window:i]
            idx_chunk = idx_aligned.iloc[i - window:i]
            down_mask = idx_chunk < 0
            if down_mask.sum() < min_down_days:
                continue
            down_chunk = chunk.loc[down_mask]
            down_chunk = down_chunk.dropna(axis=1, thresh=int(len(down_chunk) * 0.9))
            if down_chunk.shape[1] < 5 or down_chunk.shape[0] < min_down_days:
                continue
            down_chunk = down_chunk.fillna(down_chunk.median())
            try:
                pca = PCA(n_components=1)
                pca.fit(down_chunk.values)
                out.iloc[i] = pca.explained_variance_ratio_[0]
            except Exception:
                pass
        return out

    @staticmethod
    def s_liquidity_down(stocks_long: pd.DataFrame, idx_returns: pd.Series,
                         window: int = 20, min_down_days: int = 5) -> pd.Series:
        """Cross-sectional median Amihud on DOWN-MARKET days only."""
        df = stocks_long.copy()
        df['ret_abs'] = df.groupby('ticker')['close'].pct_change().abs()
        dollar_vol = (df['close'] * df['volume']).replace(0, np.nan)
        df['amihud'] = df['ret_abs'] / dollar_vol
        idx_series = idx_returns.to_frame('idx_ret')
        idx_series.index.name = 'time'
        df = df.merge(idx_series, on='time', how='left')
        df_down = df[df['idx_ret'] < 0].copy()
        if len(df_down) < min_down_days:
            return pd.Series(index=stocks_long['time'].unique(), dtype=float)
        daily = df_down.groupby('time')['amihud'].median()
        return daily.rolling(window).mean()

    # ---- main compute ----

    def compute_all(self, idx_close: pd.Series, idx_volume: pd.Series,
                    stock_returns: pd.DataFrame, stocks_long: pd.DataFrame,
                    deposit_rate: float = 0.06,
                    mode: str = 'downside') -> pd.DataFrame:
        """
        Compute all 5 pillars.

        Parameters
        ----------
        mode : 'classic' or 'downside'
            classic  = symmetric pillars
            downside = S_VOL_DOWN, S_COR_DOWN, S_LIQ_DOWN (others unchanged)
        """
        if mode == 'downside':
            s_vol = self.s_vol_down(idx_close)
            s_cor = self.s_correlation_down(stock_returns, idx_close.pct_change())
            s_liq = self.s_liquidity_down(stocks_long, idx_close.pct_change())
        else:
            s_vol = self.s_vol(idx_close)
            s_cor = self.s_correlation(stock_returns)
            s_liq = self.s_liquidity(stocks_long)

        s_pres = self.s_pressure(idx_close, idx_volume)
        s_val = self.s_valuation(idx_close, deposit_rate)

        pillars = pd.DataFrame({
            'S_VOL': s_vol,
            'S_PRES': s_pres,
            'S_COR': s_cor,
            'S_LIQ': s_liq,
            'S_VAL': s_val,
        })
        return pillars


# ──────────────────────────────────────────────
# SSI Aggregator
# ──────────────────────────────────────────────
@dataclass
class SSIResult:
    """Bundle of all aggregator outputs."""
    ssi: pd.Series                    # composite stress ∈ [0, 1]
    weights_history: pd.DataFrame     # time × pillars (PCA weights)
    pca_concentration: pd.Series      # PC1 explained variance ratio
    ranks: pd.DataFrame               # time × pillars (percentile ranks)


class SSIAggregator:
    """
    Expanding-window PCA on rank-transformed pillars.
    Look-ahead-free by construction: at time t, only [0, t] data is used.
    """

    def __init__(self, pca_warmup: int = 252, anchor_pillar: str = 'S_VOL'):
        self.pca_warmup = pca_warmup
        self.anchor_pillar = anchor_pillar

    def compute(self, pillars: pd.DataFrame, ema_span: int = 20) -> SSIResult:
        warmup = self.pca_warmup
        anchor = self.anchor_pillar

        df = pillars.dropna().copy()
        if len(df) < warmup + 1:
            raise ValueError(
                f"Insufficient data: need ≥ {warmup + 1} clean rows, got {len(df)}. "
                f"Extend date range."
            )

        cols = df.columns.tolist()
        if anchor not in cols:
            raise ValueError(f"Anchor pillar {anchor!r} not in columns {cols}")
        anchor_pos = cols.index(anchor)
        n_features = len(cols)
        idx = df.index
        values = df.values

        ssi = pd.Series(index=idx, dtype=float, name='SSI')
        concentration = pd.Series(index=idx, dtype=float, name='PCA_EVR')
        weights_hist = pd.DataFrame(index=idx, columns=cols, dtype=float)
        ranks_out = pd.DataFrame(index=idx, columns=cols, dtype=float)

        for i in range(warmup, len(df)):
            train = values[:i]
            current = values[i]

            # Expanding percentile rank of TRAIN itself
            ranks_train = (np.argsort(np.argsort(train, axis=0), axis=0) / max(i - 1, 1))

            # CDF rank of CURRENT vs TRAIN only — no look-ahead
            rank_now = (train <= current).mean(axis=0)

            try:
                pca = PCA(n_components=1)
                pca.fit(ranks_train)
                comp = pca.components_[0]
                if comp[anchor_pos] < 0:
                    comp = -comp
                if (comp < 0).any():
                    comp = np.abs(comp)
                weights = comp / comp.sum()
                evr = float(pca.explained_variance_ratio_[0])
            except Exception:
                weights = np.ones(n_features) / n_features
                evr = np.nan

            ssi.iloc[i] = float((rank_now * weights).sum())
            concentration.iloc[i] = evr
            weights_hist.iloc[i] = weights
            ranks_out.iloc[i] = rank_now

        # EMA smoothing
        if ema_span > 1 and len(ssi.dropna()) > ema_span:
            ssi_smooth = ssi.ewm(span=ema_span, adjust=False).mean()
        else:
            ssi_smooth = ssi

        return SSIResult(
            ssi=ssi_smooth,
            weights_history=weights_hist,
            pca_concentration=concentration,
            ranks=ranks_out,
        )


# ──────────────────────────────────────────────
# HMM Regime Classifier
# ──────────────────────────────────────────────
class HMMRegimeClassifier:
    """2-state Gaussian HMM on SSI series → binary HIGH_STRESS regime."""

    def __init__(self, n_states: int = 2, random_state: int = 42, n_iter: int = 200):
        self.n_states = n_states
        self.random_state = random_state
        self.n_iter = n_iter
        self.model = None
        self.high_state = None

    def fit_predict(self, ssi: pd.Series) -> pd.Series:
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            logger.warning("hmmlearn unavailable. Skipping HMM.")
            return pd.Series(index=ssi.index, dtype=float)

        clean = ssi.dropna()
        if len(clean) < 50:
            logger.warning(f"Too few SSI points ({len(clean)}) for HMM.")
            return pd.Series(index=ssi.index, dtype=float)

        X = clean.values.reshape(-1, 1)
        self.model = GaussianHMM(
            n_components=self.n_states,
            covariance_type='full',
            random_state=self.random_state,
            n_iter=self.n_iter,
        )
        self.model.fit(X)
        states = self.model.predict(X)

        means = self.model.means_.flatten()
        self.high_state = int(np.argmax(means))
        regime = (states == self.high_state).astype(int)

        out = pd.Series(index=ssi.index, dtype=float, name='Regime')
        out.loc[clean.index] = regime
        return out

    def implied_threshold(self) -> Optional[float]:
        """SSI value where P(HIGH_STRESS|x) = 0.5 (equal-prior assumption)."""
        if self.model is None or self.high_state is None:
            return None

        mus = self.model.means_.flatten()
        sigmas = np.sqrt(np.array([c[0, 0] for c in self.model.covars_]))
        mu0, mu1 = float(mus[0]), float(mus[1])
        s0, s1 = float(sigmas[0]), float(sigmas[1])

        if abs(s0 - s1) < 1e-9:
            return (mu0 + mu1) / 2.0

        a = 1.0 / (2 * s0 ** 2) - 1.0 / (2 * s1 ** 2)
        b = mu1 / s1 ** 2 - mu0 / s0 ** 2
        c_ = mu0 ** 2 / (2 * s0 ** 2) - mu1 ** 2 / (2 * s1 ** 2) - np.log(s1 / s0)
        disc = b ** 2 - 4 * a * c_

        if disc < 0 or abs(a) < 1e-12:
            return (mu0 + mu1) / 2.0

        sqrt_disc = np.sqrt(disc)
        roots = [(-b + sqrt_disc) / (2 * a), (-b - sqrt_disc) / (2 * a)]
        lo, hi = sorted([mu0, mu1])
        between = [r for r in roots if lo <= r <= hi]
        return between[0] if between else (mu0 + mu1) / 2.0

    def analyze(self, ssi: pd.Series):
        """Convenience: fit + predict + compute threshold + stats."""
        regime = self.fit_predict(ssi)
        threshold = self.implied_threshold()
        state_means = None
        state_stds = None
        if self.model is not None:
            mus = self.model.means_.flatten()
            sigmas = np.sqrt(np.array([c[0, 0] for c in self.model.covars_]))
            mu_low, mu_high = sorted(mus)
            sd_low = sigmas[np.argmin(mus)]
            sd_high = sigmas[np.argmax(mus)]
            state_means = (mu_low, mu_high)
            state_stds = (sd_low, sd_high)
        return regime, threshold, state_means, state_stds


# ──────────────────────────────────────────────
# Market State Classification
# ──────────────────────────────────────────────
MARKET_STATES = {
    'EUPHORIC_RISK': {
        'label': 'EUPHORIC RISK',
        'emoji': '🔥',
        'color': '#d68910',
        'fill_color': 'rgba(241,196,15,0.50)',
        'bg': '#fef9e7',
        'description': 'High stress + uptrend → stretched, vulnerable to shock',
    },
    'ACTIVE_STRESS': {
        'label': 'ACTIVE STRESS',
        'emoji': '🔴',
        'color': '#c0392b',
        'fill_color': 'rgba(231,76,60,0.50)',
        'bg': '#fdedec',
        'description': 'High stress + downtrend → sustained selling pressure',
    },
    'HEALTHY': {
        'label': 'HEALTHY',
        'emoji': '✅',
        'color': '#27ae60',
        'fill_color': 'rgba(46,204,113,0.30)',
        'bg': '#eafaf1',
        'description': 'Low stress + uptrend → healthy bull conditions',
    },
    'CALM_CORRECTION': {
        'label': 'CALM CORRECTION',
        'emoji': '🔵',
        'color': '#2980b9',
        'fill_color': 'rgba(52,152,219,0.40)',
        'bg': '#eaf2f8',
        'description': 'Low stress + downtrend → orderly correction, resetting',
    },
}


def classify_market_state(regime: pd.Series, idx_close: pd.Series,
                          ma_window: int = 200) -> Tuple[pd.Series, pd.Series]:
    """
    Combine HMM stress regime (1=HIGH, 0=LOW) with trend filter
    (idx_close > MA) into 4-state label series.
    """
    ma = idx_close.rolling(ma_window, min_periods=max(ma_window // 2, 20)).mean()
    trend_up_raw = (idx_close > ma)
    trend_up = trend_up_raw.reindex(regime.index)
    is_stress = (regime == 1)

    states = pd.Series(index=regime.index, dtype=object)
    valid = regime.notna() & trend_up.notna()
    states.loc[valid & is_stress & trend_up.fillna(False)] = 'EUPHORIC_RISK'
    states.loc[valid & is_stress & ~trend_up.fillna(True)] = 'ACTIVE_STRESS'
    states.loc[valid & ~is_stress & trend_up.fillna(False)] = 'HEALTHY'
    states.loc[valid & ~is_stress & ~trend_up.fillna(True)] = 'CALM_CORRECTION'
    return states, trend_up


# ──────────────────────────────────────────────
# Convenience: full pipeline
# ──────────────────────────────────────────────
def run_esr_pipeline(
    df_close: pd.DataFrame,
    df_vn30: pd.DataFrame,
    deposit_rate: float = 0.06,
    pillar_mode: str = 'downside',
    pca_warmup: int = 252,
    ema_span: int = 20,
) -> Tuple[pd.DataFrame, SSIResult, Optional[pd.Series], Optional[float]]:
    """
    Full ESR pipeline from raw data.

    Dùng VN30 index làm index chính cho S_VOL, S_PRES, S_VAL, trend filter.
    Dùng VN30 constituent returns cho S_COR (systemic correlation).

    Returns
    -------
    pillars : DataFrame (5 pillars + INDEX_Close + SSI + Market_State + HMM_Regime)
    result  : SSIResult
    market_states : Optional pd.Series (4-state classification)
    threshold : Optional float (HMM decision boundary)
    """
    # Filter VN30 tickers
    tickers = [t for t in VN30_TICKERS if t in df_close.columns]
    if len(tickers) < 10:
        raise ValueError(f"Not enough VN30 tickers: {len(tickers)}/30")

    prices = df_close[tickers].sort_index().ffill()
    rets = prices.pct_change().dropna(how='all')

    # VN30 index (load from vn30_cache.csv)
    idx_col = 'VN30' if 'VN30' in df_vn30.columns else df_vn30.columns[0]
    idx_df = df_vn30[[idx_col]].rename(columns={idx_col: 'close'}).sort_index().ffill()

    # Volume proxy: use 1e9 flat (since we don't have real volume in data_lake)
    vol_proxy = pd.Series(1e9, index=idx_df.index)

    # Align index and stocks
    common = idx_df.index.intersection(rets.index)
    idx_close = idx_df.loc[common, 'close']
    idx_volume = vol_proxy.loc[common]
    rets = rets.loc[common]

    # Build stocks_long for Amihud
    dates_long = np.repeat(rets.index.values, len(tickers))
    tickers_long = np.tile(tickers, len(rets))
    closes_long = prices.loc[rets.index, tickers].values.flatten()
    volumes_long = np.ones(len(dates_long)) * 1e6

    stocks_long = pd.DataFrame({
        'time': dates_long,
        'ticker': tickers_long,
        'close': closes_long,
        'volume': volumes_long,
    })

    # Compute pillars
    engine = PillarEngine()
    pillars = engine.compute_all(
        idx_close, idx_volume, rets, stocks_long,
        deposit_rate=deposit_rate, mode=pillar_mode,
    )

    # Aggregate SSI
    aggregator = SSIAggregator(pca_warmup=pca_warmup)
    result = aggregator.compute(pillars, ema_span=ema_span)

    # HMM regime classifier
    classifier = HMMRegimeClassifier()
    regime_series, threshold, state_means, state_stds = classifier.analyze(result.ssi)

    # 4-state market classification
    if regime_series is not None and not regime_series.dropna().empty:
        market_states, trend_up = classify_market_state(regime_series, idx_close)
    else:
        market_states = None

    # Attach metadata
    pillars['INDEX_Close'] = idx_close.reindex(pillars.index)
    pillars['SSI'] = result.ssi.reindex(pillars.index)
    if market_states is not None:
        pillars['Market_State'] = market_states.reindex(pillars.index)
    if regime_series is not None:
        pillars['HMM_Regime'] = regime_series.reindex(pillars.index)

    return pillars, result, market_states, threshold
