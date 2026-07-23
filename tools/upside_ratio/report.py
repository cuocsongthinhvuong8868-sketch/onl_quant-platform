from tools.upside_ratio.quant.metrics import build_breadth_series, summarize_breadth_state
from tools.upside_ratio.quant.engine import DEFAULT_MC_SEED, run_hybrid_ensemble_mc


def snapshot(df_close, _load_custom):
    data = build_breadth_series(df_close, upside_x=2.0, downside_y=-2.0, lookback_days=90)
    up = run_hybrid_ensemble_mc(
        data["raw_upside"], days_to_sim=10, num_sims=3000, seed=DEFAULT_MC_SEED
    )
    dn = run_hybrid_ensemble_mc(
        data["raw_downside"], days_to_sim=10, num_sims=3000, seed=DEFAULT_MC_SEED + 1
    )
    _, _, p50_up, _, _, phi_up, mu_up, _, _ = up
    _, _, p50_dn, _, _, phi_dn, mu_dn, _, _ = dn
    summary = summarize_breadth_state(data)
    return {
        "snapshot_date": data["raw_upside"].index[-1].strftime("%Y-%m-%d"),
        "methodology_version": summary["methodology_version"],
        "upside_current": round(float(data["raw_upside"].iloc[-1]), 3),
        "downside_current": round(float(data["raw_downside"].iloc[-1]), 3),
        "upside_ma5": round(float(summary["upside_ma5"]), 3),
        "downside_ma5": round(float(summary["downside_ma5"]), 3),
        "upside_rank": round(float(summary["upside_rank"]), 4),
        "downside_rank": round(float(summary["downside_rank"]), 4),
        "net_pressure": round(float(summary["net_pressure"]), 3),
        "ma5_net_pressure": round(float(summary["ma5_net_pressure"]), 3),
        "breadth_stress_score": round(float(summary["breadth_stress_score"]), 2),
        "breadth_stress_level": summary["breadth_stress_level"],
        "breadth_regime": summary["breadth_regime"],
        "upside_median_t9": round(float(p50_up[-1]), 3),
        "downside_median_t9": round(float(p50_dn[-1]), 3),
        "phi_up": round(float(phi_up), 4),
        "phi_down": round(float(phi_dn), 4),
        "mu_up": round(float(mu_up), 4),
        "mu_down": round(float(mu_dn), 4),
    }
