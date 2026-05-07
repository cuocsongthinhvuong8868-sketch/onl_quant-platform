import streamlit as st
from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.esr_monitor.quant.metrics import calculate_esr
from tools.esr_monitor.ui.charts import render_esr_chart


def render():
    st.title("ESR Monitor")
    st.caption("Systemic stress monitor (proxy) cho VN30 cluster")

    ma_period = st.sidebar.slider("MA period", 50, 250, 125)
    pca_window = st.sidebar.slider("PCA window", 30, 120, 60)

    try:
        df_close = load_close_prices()
        df_index = load_custom("vnindex_cache.csv")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_close.index.max().strftime('%d/%m/%Y')}")

    key = {"ma_period": ma_period, "pca_window": pca_window}
    cached = load_daily_cache("esr_monitor", key)
    if cached is not None:
        df = cached["df"]
        weights = cached["weights"]
        st.caption("⚡ Dùng cache cùng ngày (ESR Monitor).")
    else:
        with st.spinner("Đang tính ESR..."):
            try:
                df, weights = calculate_esr(df_close, df_index, ma_period=ma_period, pca_window=pca_window)
            except Exception as e:
                st.error(f"Không tính được ESR: {e}")
                st.stop()
        save_daily_cache("esr_monitor", key, {"df": df, "weights": weights})
        st.caption("💾 Đã tạo cache ngày mới (ESR Monitor).")

    last = df.iloc[-1]
    status = "SAFE" if last["SSI_Index"] < 0.5 else "WARNING" if last["SSI_Index"] < 0.8 else "CRITICAL"
    c1, c2, c3 = st.columns(3)
    c1.metric("SSI", f"{last['SSI_Index']:.2%}")
    c2.metric("Status", status)
    c3.metric("Index", f"{last['INDEX_Close']:.2f}")

    st.subheader("Risk Contribution (PCA)")
    st.bar_chart(weights)

    st.subheader("SSI vs Index")
    render_esr_chart(df)
