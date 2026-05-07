import logging
import numpy as np
import pandas as pd
from arch import arch_model

logger = logging.getLogger(__name__)


def fit_egarch(market_factor: pd.Series) -> pd.Series:
    """
    Fit EGARCH(1,1,1) với phân phối Hansen Skewed-T.

    Lý do chọn mô hình này
    ----------------------
    - EGARCH: bắt được leverage effect (tin xấu → vol tăng mạnh hơn tin tốt).
    - Skewed-T: thị trường VN có fat tail và lệch trái — normal distribution
      đánh giá thấp rủi ro đuôi.

    Trả về
    ------
    Annualised conditional volatility (× √252).

    Raises
    ------
    RuntimeError nếu model không hội tụ.
    """
    y = np.ascontiguousarray(market_factor.values * 100, dtype=np.float64)

    try:
        res = arch_model(y, vol="EGARCH", p=1, o=1, q=1, dist="skewstudent").fit(
            update_freq=0, disp="off"
        )
        logger.info("EGARCH hội tụ — Log-lik: %.2f | AIC: %.2f",
                    res.loglikelihood, res.aic)
        ann_vol = (res.conditional_volatility / 100) * np.sqrt(252)
        return pd.Series(ann_vol, index=market_factor.index, name="EGARCH_Vol")

    except Exception as exc:
        raise RuntimeError(f"EGARCH không hội tụ: {exc}") from exc
