import logging
import numpy as np
import pandas as pd
from arch import arch_model

logger = logging.getLogger(__name__)

# EWMA decay theo RiskMetrics 1996 cho daily: λ=0.94 → halflife ≈ 11 ngày
EWMA_LAMBDA = 0.94


def _ewma_volatility(returns_pct: np.ndarray) -> np.ndarray:
    """RiskMetrics EWMA: σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}.

    Fallback cuối cùng — luôn produce non-NaN output (trừ phần warmup).
    Trả về annualized vol ở scale gốc (chia 100 để hoàn nguyên về fraction).
    """
    n = len(returns_pct)
    var_t = np.full(n, np.nan)
    seed_var = np.nanvar(returns_pct[: min(30, n)])
    if not np.isfinite(seed_var) or seed_var <= 0:
        seed_var = 1.0
    var_t[0] = seed_var
    for t in range(1, n):
        prev_var = var_t[t - 1] if np.isfinite(var_t[t - 1]) else seed_var
        r2 = returns_pct[t - 1] ** 2 if np.isfinite(returns_pct[t - 1]) else 0.0
        var_t[t] = EWMA_LAMBDA * prev_var + (1.0 - EWMA_LAMBDA) * r2
    sigma = np.sqrt(var_t)
    return (sigma / 100.0) * np.sqrt(252)


def fit_egarch(market_factor: pd.Series) -> pd.Series:
    """
    Conditional volatility với fallback 3 bậc:
      1) EGARCH(1,1,1) Skewed-T  — leverage effect + fat tails (mặc định, chất lượng cao nhất)
      2) GARCH(1,1) Gaussian     — fallback khi EGARCH Skewed-T không hội tụ
      3) RiskMetrics EWMA (λ=0.94) — fallback cuối, không bao giờ fail

    Pipeline AI CIO / backtest từng crash khi EGARCH không hội tụ (data nhiễu,
    đoạn flat sau pause giao dịch). Giờ luôn return Series hợp lệ và log rõ
    method nào đã dùng để diagnostic.

    Trả về
    ------
    Annualised conditional volatility (× √252).
    """
    y = np.ascontiguousarray(market_factor.values * 100, dtype=np.float64)

    # Tier 1: EGARCH Skewed-T
    try:
        res = arch_model(y, vol="EGARCH", p=1, o=1, q=1, dist="skewstudent").fit(
            update_freq=0, disp="off"
        )
        if getattr(res, "convergence_flag", 0) == 0:
            logger.info(
                "EGARCH Skewed-T hội tụ — Log-lik: %.2f | AIC: %.2f",
                res.loglikelihood, res.aic,
            )
            ann_vol = (res.conditional_volatility / 100) * np.sqrt(252)
            return pd.Series(ann_vol, index=market_factor.index, name="EGARCH_Vol")
        logger.warning("EGARCH Skewed-T convergence_flag != 0 — thử fallback.")
    except Exception as exc:
        logger.warning("EGARCH Skewed-T fail: %s — thử GARCH(1,1) Gaussian.", exc)

    # Tier 2: GARCH(1,1) Gaussian
    try:
        res = arch_model(y, vol="GARCH", p=1, q=1, dist="normal").fit(
            update_freq=0, disp="off"
        )
        if getattr(res, "convergence_flag", 0) == 0:
            logger.info(
                "Fallback GARCH(1,1) Gaussian hội tụ — Log-lik: %.2f | AIC: %.2f",
                res.loglikelihood, res.aic,
            )
            ann_vol = (res.conditional_volatility / 100) * np.sqrt(252)
            return pd.Series(ann_vol, index=market_factor.index, name="EGARCH_Vol")
        logger.warning("GARCH(1,1) convergence_flag != 0 — fallback EWMA.")
    except Exception as exc:
        logger.warning("GARCH(1,1) fail: %s — fallback EWMA.", exc)

    # Tier 3: RiskMetrics EWMA — luôn produce output
    logger.warning("Sử dụng EWMA λ=%.2f làm fallback cuối. Vol sẽ kém phản ánh leverage/skew.", EWMA_LAMBDA)
    ann_vol = _ewma_volatility(y)
    return pd.Series(ann_vol, index=market_factor.index, name="EGARCH_Vol")
