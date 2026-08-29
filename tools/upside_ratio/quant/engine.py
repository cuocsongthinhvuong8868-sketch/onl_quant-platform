import numpy as np
import pandas as pd
from statsmodels.tsa.ar_model import AutoReg

DEFAULT_MC_SEED = 42


def run_hybrid_ensemble_mc(
    raw_ratio_series: pd.Series,
    days_to_sim: int = 20,
    num_sims: int = 3000,
    seed: int | None = DEFAULT_MC_SEED,
):
    """Hybrid ensemble Monte Carlo for bounded breadth ratios [0, 100].

    ``seed`` mặc định cố định để cùng input/parameters tạo cùng output. Truyền
    ``None`` chỉ khi chủ động muốn một simulation ngẫu nhiên không tái lập.
    """
    if len(raw_ratio_series) < 30:
        raise ValueError("Không đủ dữ liệu để chạy mô hình (cần tối thiểu 30 điểm).")
    if days_to_sim < 1 or num_sims < 1:
        raise ValueError("days_to_sim và num_sims phải >= 1")

    rng = np.random.default_rng(seed)
    p_raw = np.clip(raw_ratio_series.values, 0.1, 99.9) / 100.0
    last_p = p_raw[-1]

    # Engine 1: Logit bootstrap AR(1)
    y = np.log(p_raw / (1.0 - p_raw))
    # ``old_names=False`` was the default in statsmodels 0.14 and the keyword
    # was removed in 0.15. Omitting it preserves the same parameter naming and
    # keeps the GitHub Actions dependency range (>=0.14,<0.16) compatible.
    model_ar = AutoReg(y, lags=1).fit()
    c_emp = model_ar.params[0]
    phi_emp = model_ar.params[1]
    resid_emp = model_ar.resid

    sim_y = np.zeros((days_to_sim, num_sims))
    sim_y[0, :] = c_emp + phi_emp * y[-1] + rng.choice(resid_emp, size=num_sims, replace=True)
    for t in range(1, days_to_sim):
        sim_y[t, :] = c_emp + phi_emp * sim_y[t - 1, :] + rng.choice(
            resid_emp, size=num_sims, replace=True
        )
    sim_p_emp = 1.0 / (1.0 + np.exp(-sim_y))

    # Engine 2: Beta AR approximation
    p_t = p_raw[1:]
    p_tm1 = p_raw[:-1]
    cov_matrix = np.cov(p_t, p_tm1)
    phi_beta = cov_matrix[0, 1] / (cov_matrix[1, 1] + 1e-10)
    phi_beta = np.clip(phi_beta, -0.95, 0.95)
    mu_beta = p_raw.mean()

    resid_beta = p_t - (mu_beta * (1.0 - phi_beta) + phi_beta * p_tm1)
    sigma_beta = max(resid_beta.std(), 0.05)

    sim_p_beta = np.zeros((days_to_sim, num_sims))
    sim_p_beta[0, :] = last_p
    for t in range(1, days_to_sim):
        mean_t = mu_beta * (1.0 - phi_beta) + phi_beta * sim_p_beta[t - 1, :]
        mean_t = np.clip(mean_t, 0.001, 0.999)
        kappa = mean_t * (1.0 - mean_t) / (sigma_beta ** 2) - 1.0
        kappa = np.maximum(kappa, 0.5)
        sim_p_beta[t, :] = rng.beta(mean_t * kappa, (1.0 - mean_t) * kappa)

    pooled_sim_p = np.hstack((sim_p_emp, sim_p_beta)) * 100.0
    total_sims = num_sims * 2

    past_4_days = raw_ratio_series.values[-4:]
    past_4_matrix = np.tile(past_4_days, (total_sims, 1)).T
    full_sim_p = np.vstack((past_4_matrix, pooled_sim_p))

    sim_ma5 = np.zeros_like(pooled_sim_p)
    for t in range(days_to_sim):
        sim_ma5[t, :] = np.mean(full_sim_p[t : t + 5, :], axis=0)

    p5 = np.percentile(sim_ma5, 5, axis=1)
    p25 = np.percentile(sim_ma5, 25, axis=1)
    p50 = np.percentile(sim_ma5, 50, axis=1)
    p75 = np.percentile(sim_ma5, 75, axis=1)
    p95 = np.percentile(sim_ma5, 95, axis=1)

    return p5, p25, p50, p75, p95, phi_beta, mu_beta, resid_emp, resid_beta
