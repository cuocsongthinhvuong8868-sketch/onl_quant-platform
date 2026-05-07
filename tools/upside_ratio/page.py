import logging
import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.upside_ratio.quant.metrics import build_breadth_series
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc
from tools.upside_ratio.ui.sidebar import render_sidebar
from tools.upside_ratio.ui.charts import render_history_chart, render_projection_tabs, render_diagnostics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def render():
    st.title("Hybrid MC Bidirectional Breadth")
    st.caption("Upside/Downside breadth ratio với Hybrid Monte Carlo ensemble")

    params = render_sidebar()

    try:
        df_close = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_close.index.max().strftime('%d/%m/%Y')}")

    try:
        df_index = load_custom("vnindex_cache.csv")
    except FileNotFoundError:
        df_index = None

    key = {
        "upside_x": params["upside_x"],
        "downside_y": params["downside_y"],
        "lookback_days": params["lookback_days"],
        "sim_days": params["sim_days"],
    }
    cached = load_daily_cache("upside_ratio", key)
    if cached is not None:
        data = cached["data"]
        up_tuple = cached["up_tuple"]
        dn_tuple = cached["dn_tuple"]
        st.caption("⚡ Dùng cache cùng ngày (Upside Ratio).")
    else:
        with st.spinner("Dang tinh breadth + mo phong Monte Carlo..."):
            try:
                data = build_breadth_series(
                    df_close,
                    upside_x=params["upside_x"],
                    downside_y=params["downside_y"],
                    lookback_days=params["lookback_days"],
                )
                up_tuple = run_hybrid_ensemble_mc(data["raw_upside"], days_to_sim=params["sim_days"], num_sims=3000)
                dn_tuple = run_hybrid_ensemble_mc(data["raw_downside"], days_to_sim=params["sim_days"], num_sims=3000)
            except (ValueError, RuntimeError) as e:
                st.error(f"Loi mo hinh: {e}")
                st.stop()
        save_daily_cache("upside_ratio", key, {"data": data, "up_tuple": up_tuple, "dn_tuple": dn_tuple})
        st.caption("💾 Đã tạo cache ngày mới (Upside Ratio).")

    _, _, p50_up, _, _, phi_up, mu_up, _, _ = up_tuple
    _, _, p50_dn, _, _, phi_dn, mu_dn, _, _ = dn_tuple

    regime_up = "Momentum" if phi_up > 0.1 else "Mean-reversion" if phi_up < -0.1 else "Random walk"
    regime_dn = "Momentum" if phi_dn > 0.1 else "Mean-reversion" if phi_dn < -0.1 else "Random walk"

    a, b, c, d = st.columns(4)
    a.metric("Phi Upside", f"{phi_up:.3f}", regime_up)
    b.metric("Mu Upside", f"{mu_up*100:.1f}%")
    c.metric("Phi Downside", f"{phi_dn:.3f}", regime_dn)
    d.metric("Mu Downside", f"{mu_dn*100:.1f}%")

    st.subheader("1. Lich su Cung - Cau")
    render_history_chart(
        data["raw_upside"], data["ma5_upside"],
        data["raw_downside"], data["ma5_downside"],
        mu_up, mu_dn, df_index=df_index,
    )

    st.subheader(f"2. Du phong Monte Carlo ({params['sim_days']} phien)")
    resid_up, resid_dn = render_projection_tabs(
        data["raw_upside"], data["ma5_upside"],
        data["raw_downside"], data["ma5_downside"],
        params["sim_days"], up_tuple, dn_tuple,
    )

    st.info(
        f"Upside median T+{params['sim_days']-1}: {p50_up[-1]:.1f}% | "
        f"Downside median T+{params['sim_days']-1}: {p50_dn[-1]:.1f}%"
    )

    render_diagnostics(data["raw_upside"], data["raw_downside"], resid_up, resid_dn)
