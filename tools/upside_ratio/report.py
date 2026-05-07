from tools.upside_ratio.quant.metrics import build_breadth_series
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc


def snapshot(df_close, _load_custom):
    data = build_breadth_series(df_close, upside_x=2.0, downside_y=-2.0, lookback_days=90)
    up = run_hybrid_ensemble_mc(data["raw_upside"], days_to_sim=10, num_sims=3000)
    dn = run_hybrid_ensemble_mc(data["raw_downside"], days_to_sim=10, num_sims=3000)
    _, _, p50_up, _, _, phi_up, mu_up, _, _ = up
    _, _, p50_dn, _, _, phi_dn, mu_dn, _, _ = dn
    return {
        "snapshot_date": data["raw_upside"].index[-1].strftime("%Y-%m-%d"),
        "upside_current": round(float(data["raw_upside"].iloc[-1]), 3),
        "downside_current": round(float(data["raw_downside"].iloc[-1]), 3),
        "upside_median_t9": round(float(p50_up[-1]), 3),
        "downside_median_t9": round(float(p50_dn[-1]), 3),
        "phi_up": round(float(phi_up), 4),
        "phi_down": round(float(phi_dn), 4),
        "mu_up": round(float(mu_up), 4),
        "mu_down": round(float(mu_dn), 4),
    }
