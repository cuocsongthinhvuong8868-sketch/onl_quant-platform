from shared.data_loader import load_custom, load_volumes
from tools.esr_monitor.quant.metrics import (
    run_esr_pipeline, VN30_TICKERS,
    PRODUCTION_DEPOSIT_RATE, PRODUCTION_PILLAR_MODE, PRODUCTION_PCA_WARMUP,
    PRODUCTION_EMA_SPAN, PRODUCTION_REGIME_METHOD,
)


def snapshot(df_close, _load_custom):
    df_vn30 = load_custom("vn30_cache.csv")
    df_volume = load_volumes()
    # Report snapshot CSV — dùng PRODUCTION_REGIME_METHOD (single source of truth).
    # Đồng bộ với ESR Monitor LIVE default và AI CIO AUTO.
    pillars, result, market_states, threshold = run_esr_pipeline(
        df_close, df_vn30,
        df_volume=df_volume,
        deposit_rate=PRODUCTION_DEPOSIT_RATE,
        pillar_mode=PRODUCTION_PILLAR_MODE,
        pca_warmup=PRODUCTION_PCA_WARMUP,
        ema_span=PRODUCTION_EMA_SPAN,
        regime_method=PRODUCTION_REGIME_METHOD,
    )
    last_ssi = result.ssi.dropna().iloc[-1]
    last_idx = pillars['INDEX_Close'].dropna().iloc[-1]
    last_evr = result.pca_concentration.dropna().iloc[-1]
    last_w = result.weights_history.dropna().iloc[-1].to_dict()

    # Determine status
    if market_states is not None and not market_states.empty:
        state_key = market_states.dropna().iloc[-1]
        status = state_key
    else:
        status = "SAFE" if last_ssi < 0.5 else "WARNING" if last_ssi < 0.8 else "CRITICAL"

    return {
        "snapshot_date": pillars.index[-1].strftime("%Y-%m-%d"),
        "ssi": round(float(last_ssi), 6),
        "index_close": round(float(last_idx), 2),
        "pca_concentration": round(float(last_evr), 6),
        "pca_weights": {k: round(v, 4) for k, v in last_w.items()},
        "status": status,
        "n_tickers": sum(1 for t in VN30_TICKERS if t in df_close.columns),
    }
