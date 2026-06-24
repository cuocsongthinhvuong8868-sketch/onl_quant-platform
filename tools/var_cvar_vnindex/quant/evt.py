"""
Extreme Value Theory (EVT) — Peaks-Over-Threshold + Generalized Pareto Distribution
====================================================================================

Tail-risk estimator chuẩn vàng tại Basel III, BIS, JPM CIB Risk, AQR Tail Risk.

Tại sao EVT?
------------
- **Historical VaR_99%** cần ~300 obs trong tail để ổn định → noisy với 3 năm data
  (chỉ có ~7 obs trong tail 99%). Estimator của 1-2 ngày extreme nhất chi phối.
- **Parametric VaR (Gaussian)** đánh giá thấp tail risk 2-3× cho VN-Index vì
  return không phân phối chuẩn (skew âm + kurt > 3).
- **EVT POT-GPD** fit phân phối chỉ vào TAIL (top 10% losses) → mô hình hoá đúng
  hình dạng đuôi → extrapolate sang quantile cực đoan (99%, 99.5%, 99.9%) đáng tin.

Pickands–Balkema–de Haan (1974, 1975):
    Nếu L là biến ngẫu nhiên thuộc class GEV (Generalized Extreme Value), thì
    với threshold u đủ cao, exceedances (L - u | L > u) → GPD(ξ, β) khi u → x_F.

Tài liệu tham khảo
------------------
- McNeil, Frey, Embrechts (2015) — *Quantitative Risk Management*, Ch. 7
- Coles (2001) — *An Introduction to Statistical Modeling of Extreme Values*
- Embrechts, Klüppelberg, Mikosch (1997) — *Modelling Extremal Events*
"""
from __future__ import annotations

import logging
import warnings
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import genpareto

logger = logging.getLogger(__name__)

# ── Defaults (theo McNeil-Frey-Embrechts) ──
DEFAULT_THRESHOLD_PCT = 0.10        # u = top 10% của losses
DEFAULT_MIN_EXCEEDANCES = 30        # cần ≥ 30 exceedances để MLE ổn định (asymptotic theory)
DEFAULT_ROLLING_WINDOW = 756        # 3 năm trading days
DEFAULT_REFIT_EVERY = 21            # ~1 tháng giữa các lần refit (industry standard cho monthly risk reports)
DEFAULT_QUANTILES = (0.95, 0.99, 0.995)
DEFAULT_SENSITIVITY_THRESHOLDS = (0.05, 0.075, 0.10, 0.125, 0.15)


# ──────────────────────────────────────────────────────────────────────────
# Static estimators
# ──────────────────────────────────────────────────────────────────────────

def pot_threshold(losses: np.ndarray, pct: float = DEFAULT_THRESHOLD_PCT) -> float:
    """Chọn threshold u = (1-pct)-quantile của losses.

    `pct = 0.10` → u là 90th percentile → top 10% losses là exceedances.
    Threshold quá thấp → fit GPD lên data không-tail (bias).
    Threshold quá cao → ít exceedances → MLE noisy (variance).
    Default 10% là sweet spot theo literature.
    """
    clean = losses[np.isfinite(losses)]
    return float(np.quantile(clean, 1.0 - pct))


def fit_gpd(exceedances: np.ndarray) -> Optional[Tuple[float, float]]:
    """Fit GPD(ξ, β) lên exceedances bằng Maximum Likelihood.

    GPD CDF:
        F(y; ξ, β) = 1 - (1 + ξy/β)^(-1/ξ)     nếu ξ ≠ 0
        F(y; 0, β) = 1 - exp(-y/β)              nếu ξ = 0

    Parameters
    ----------
    exceedances : positive 1-D array, y_i = L_i - u với L_i > u.

    Returns
    -------
    (xi, beta) hoặc None nếu fit fail (insufficient data hoặc pathological estimate).

    Notes
    -----
    - ξ > 0  → heavy tail (Pareto-type). Equity returns thường có ξ ∈ [0.15, 0.45].
    - ξ = 0  → exponential tail (light).
    - ξ < 0  → bounded tail (rare in finance).
    - ξ ≥ 1  → ES không định nghĩa (mean infinite).
    """
    if len(exceedances) < DEFAULT_MIN_EXCEEDANCES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # floc=0 ép vị trí về 0 (exceedances đã shift về 0)
            xi, _, beta = genpareto.fit(exceedances, floc=0)
        if not (np.isfinite(xi) and np.isfinite(beta)) or beta <= 0:
            return None
        # Reject pathological xi — financial returns không bao giờ có |ξ| > 1.5
        if abs(xi) > 1.5:
            return None
        return float(xi), float(beta)
    except Exception as exc:
        logger.debug("GPD fit failed: %s", exc)
        return None


def evt_var(quantile: float, threshold: float, xi: float, beta: float,
            n_total: int, n_exceed: int) -> float:
    """VaR tại quantile cực đoan theo GPD analytical formula.

        VaR_α = u + (β/ξ) · [(n/N_u · (1-α))^(-ξ) - 1]    nếu ξ ≠ 0
        VaR_α = u + β · log(n/N_u · 1/(1-α))               nếu ξ = 0

    Trả về **loss positive** (tổn thất là số dương). Caller chịu trách nhiệm
    chuyển sang return scale bằng cách lấy âm.

    Yêu cầu: quantile > 1 - n_exceed/n_total (tức quantile phải nằm trong tail).
    """
    p_tail = n_exceed / n_total
    p_excess = (1.0 - quantile) / p_tail
    if p_excess >= 1.0:
        # Quantile không nằm trong tail — fallback dùng empirical quantile
        return threshold
    if abs(xi) < 1e-8:
        return threshold + beta * (-np.log(p_excess))
    return threshold + (beta / xi) * (p_excess ** (-xi) - 1.0)


def evt_es(quantile: float, threshold: float, xi: float, beta: float,
           n_total: int, n_exceed: int) -> float:
    """Expected Shortfall (CVaR) tại quantile cực đoan theo GPD.

        ES_α = VaR_α/(1-ξ) + (β - ξ·u)/(1-ξ)    với ξ < 1

    Trả NaN nếu ξ ≥ 1 (mean của GPD không tồn tại → tail risk vô hạn).
    """
    if xi >= 1.0:
        return np.nan
    var_val = evt_var(quantile, threshold, xi, beta, n_total, n_exceed)
    return var_val / (1.0 - xi) + (beta - xi * threshold) / (1.0 - xi)


def hill_estimator(losses: np.ndarray, k: Optional[int] = None) -> float:
    """Hill (1975) tail index estimator — bổ sung diagnostic cho ξ của GPD.

        ξ̂_Hill = (1/k) · Σ_{i=1..k} log(L_(i) / L_(k+1))

    với L_(1) ≥ L_(2) ≥ ... là positive losses sắp xếp giảm dần.

    Default `k = floor(sqrt(n_pos))` — Hall (1990) heuristic cân bằng bias-variance.

    Hill ξ̂ và GPD ξ̂ ước lượng cùng tail index nhưng:
    - Hill chỉ valid cho ξ > 0 (heavy tail).
    - GPD valid cho mọi ξ nhưng nhạy với threshold choice.
    - Cùng dấu + magnitude tương đương → robust signal.
    """
    pos = losses[np.isfinite(losses) & (losses > 0)]
    n = len(pos)
    if n < 30:
        return np.nan
    if k is None:
        k = max(int(np.sqrt(n)), 10)
    k = min(k, n - 1)
    sorted_pos = np.sort(pos)[::-1]
    denom = sorted_pos[k]
    if denom <= 0:
        return np.nan
    return float(np.mean(np.log(sorted_pos[:k] / denom)))


# ──────────────────────────────────────────────────────────────────────────
# Window-level orchestration
# ──────────────────────────────────────────────────────────────────────────

def fit_evt_window(losses_window: np.ndarray,
                   threshold_pct: float = DEFAULT_THRESHOLD_PCT) -> Optional[dict]:
    """Fit POT-GPD lên 1 cửa sổ losses. Trả dict tham số hoặc None nếu fail."""
    losses_clean = losses_window[np.isfinite(losses_window)]
    # Cần đủ data để top 10% còn ≥ MIN_EXCEEDANCES → n_total ≥ 300
    if len(losses_clean) < DEFAULT_MIN_EXCEEDANCES * 10:
        return None

    u = pot_threshold(losses_clean, threshold_pct)
    exceedances = losses_clean[losses_clean > u] - u
    if len(exceedances) < DEFAULT_MIN_EXCEEDANCES:
        return None

    fit = fit_gpd(exceedances)
    if fit is None:
        return None
    xi, beta = fit

    return {
        'threshold': u,
        'xi': xi,
        'beta': beta,
        'n_total': len(losses_clean),
        'n_exceed': len(exceedances),
        'hill': hill_estimator(losses_clean),
    }


def evt_threshold_sensitivity(
    returns: pd.Series,
    thresholds: Tuple[float, ...] = DEFAULT_SENSITIVITY_THRESHOLDS,
    window: int = DEFAULT_ROLLING_WINDOW,
    quantiles: Tuple[float, ...] = (0.99, 0.995),
) -> pd.DataFrame:
    """Fit EVT trên nhiều POT thresholds cho cửa sổ mới nhất.

    Đây là robustness test cho lựa chọn threshold, không phải backtest coverage.
    Một model đáng tin hơn khi ``xi``, VaR và ES không đổi quá mạnh trong vùng
    threshold hợp lý 5%-15% tail losses.
    """
    clean_returns = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
    if window < 1:
        raise ValueError("window phải >= 1")
    if not thresholds:
        raise ValueError("thresholds không được rỗng")
    if any(not 0 < value < 0.5 for value in thresholds):
        raise ValueError("Mỗi threshold phải nằm trong (0, 0.5)")

    losses = -clean_returns.tail(window).to_numpy(dtype=np.float64, copy=False)
    rows: list[dict] = []

    for threshold_pct in thresholds:
        params = fit_evt_window(losses, threshold_pct=float(threshold_pct))
        row = {
            "threshold_pct": float(threshold_pct),
            "threshold_quantile": float(1.0 - threshold_pct),
            "status": "ok" if params is not None else "insufficient_or_unstable",
        }
        if params is None:
            rows.append(row)
            continue

        row.update({
            "threshold": float(params["threshold"]),
            "n_total": int(params["n_total"]),
            "n_exceed": int(params["n_exceed"]),
            "xi": float(params["xi"]),
            "beta": float(params["beta"]),
            "hill_index": float(params["hill"]),
        })
        for quantile in quantiles:
            suffix = _quantile_suffix(quantile)
            row[f"evt_var_{suffix}"] = -evt_var(
                quantile,
                params["threshold"],
                params["xi"],
                params["beta"],
                params["n_total"],
                params["n_exceed"],
            )
            row[f"evt_es_{suffix}"] = -evt_es(
                quantile,
                params["threshold"],
                params["xi"],
                params["beta"],
                params["n_total"],
                params["n_exceed"],
            )
        rows.append(row)

    return pd.DataFrame(rows).sort_values("threshold_pct").reset_index(drop=True)


def _quantile_suffix(quantile: float) -> str:
    """Map 0.99 -> '99', 0.995 -> '995'."""
    scaled_100 = quantile * 100
    if np.isclose(scaled_100, round(scaled_100)):
        return str(int(round(scaled_100)))
    return str(int(round(quantile * 1000)))


# ──────────────────────────────────────────────────────────────────────────
# Rolling EVT — production API
# ──────────────────────────────────────────────────────────────────────────

def rolling_evt_metrics(
    returns: pd.Series,
    window: int = DEFAULT_ROLLING_WINDOW,
    refit_every: int = DEFAULT_REFIT_EVERY,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    quantiles: Tuple[float, ...] = DEFAULT_QUANTILES,
) -> pd.DataFrame:
    """Rolling EVT VaR/ES tại nhiều quantile cực đoan.

    Performance: GPD MLE ~ 30-50ms/fit. Refit mỗi `refit_every=21` phiên
    (1 tháng giao dịch) thay vì daily → ~21× speedup, accuracy loss < 1%
    (params GPD thay đổi chậm với 3Y window). Đây là pattern chuẩn ở
    monthly risk reports của các sell-side risk desk.

    Parameters
    ----------
    returns : pd.Series
        Daily log-returns hoặc simple returns (negative = loss).
    window : int
        Cửa sổ rolling (default 756 = 3 năm).
    refit_every : int
        Số phiên giữa các lần refit GPD.
    threshold_pct : float
        Tỷ lệ top-losses dùng làm threshold (default 10%).
    quantiles : tuple
        Các quantile cần tính VaR/ES (default 95%, 99%, 99.5%).

    Returns
    -------
    pd.DataFrame với cột:
        evt_var_95, evt_var_99, evt_var_995  (return scale, negative)
        evt_es_95, evt_es_99, evt_es_995     (return scale, negative)
        evt_xi              (GPD shape parameter — heavy-tail indicator)
        evt_beta            (GPD scale parameter)
        evt_threshold       (loss-scale threshold u, positive)
        evt_n_exceed        (số exceedances trong window hiện tại)
        hill_index          (Hill estimator — cross-check cho ξ)
    """
    losses_arr = -returns.to_numpy(dtype=np.float64, copy=False)
    n = len(losses_arr)

    # Build column names: 0.95 → "95", 0.99 → "99", 0.995 → "995"
    def _qstr(q: float) -> str:
        return str(int(round(q * 1000))) if q * 100 != int(q * 100) else str(int(round(q * 100)))

    var_cols = [f'evt_var_{_qstr(q)}' for q in quantiles]
    es_cols = [f'evt_es_{_qstr(q)}' for q in quantiles]
    extra_cols = ['evt_xi', 'evt_beta', 'evt_threshold', 'evt_n_exceed', 'hill_index']
    all_cols = var_cols + es_cols + extra_cols

    out = pd.DataFrame(np.nan, index=returns.index, columns=all_cols)

    last_params: Optional[dict] = None
    last_fit_idx = -refit_every - 1
    n_fits = 0
    n_fit_fails = 0

    for i in range(window - 1, n):
        if i - last_fit_idx >= refit_every:
            win = losses_arr[i - window + 1: i + 1]
            params = fit_evt_window(win, threshold_pct)
            if params is not None:
                last_params = params
                last_fit_idx = i
                n_fits += 1
            else:
                n_fit_fails += 1

        if last_params is None:
            continue

        u = last_params['threshold']
        xi = last_params['xi']
        beta = last_params['beta']
        nT = last_params['n_total']
        nE = last_params['n_exceed']

        for qi, q in enumerate(quantiles):
            v = evt_var(q, u, xi, beta, nT, nE)
            e = evt_es(q, u, xi, beta, nT, nE)
            # Loss → return: âm
            out.iat[i, qi] = -v
            out.iat[i, len(quantiles) + qi] = -e
        out.iat[i, 2 * len(quantiles) + 0] = xi
        out.iat[i, 2 * len(quantiles) + 1] = beta
        out.iat[i, 2 * len(quantiles) + 2] = u
        out.iat[i, 2 * len(quantiles) + 3] = nE
        out.iat[i, 2 * len(quantiles) + 4] = last_params['hill']

    logger.info(
        "Rolling EVT: %d successful fits, %d fails, refit_every=%d days",
        n_fits, n_fit_fails, refit_every,
    )
    return out
