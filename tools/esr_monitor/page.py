import streamlit as st
from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.esr_monitor.quant.metrics import calculate_esr
from tools.esr_monitor.ui.charts import render_esr_chart
from config import AI_PROVIDER_MAP


def render():
    st.title("ESR Monitor")
    st.caption("Systemic stress monitor (proxy) cho VN30 cluster")

    ma_period = st.sidebar.slider("MA period", 50, 250, 125)
    pca_window = st.sidebar.slider("PCA window", 30, 120, 60)
    bond_yield = st.sidebar.number_input("Bond Yield hiện tại (%)", value=4.20, step=0.1) / 100

    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="esr_ai_provider",
    )
    api_key = st.sidebar.text_input("API Key", type="password", key="esr_api_key")

    try:
        df_close = load_close_prices()
        df_index = load_custom("vnindex_cache.csv")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_close.index.max().strftime('%d/%m/%Y')}")

    key = {"ma_period": ma_period, "pca_window": pca_window, "bond_yield": bond_yield}
    cached = load_daily_cache("esr_monitor", key)
    if cached is not None:
        df = cached["df"]
        weights = cached["weights"]
        st.caption("⚡ Dùng cache cùng ngày (ESR Monitor).")
    else:
        with st.spinner("Đang tính ESR..."):
            try:
                df, weights = calculate_esr(df_close, df_index, ma_period=ma_period, pca_window=pca_window, bond_yield=bond_yield)
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

    # ── AI Analysis ──
    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Rủi ro Hệ thống")

    import os
    from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    from openai import OpenAI

    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"esr_monitor_{ai_provider}_{today_str}.txt"

    if ai_cache_file.exists():
        st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
        with open(ai_cache_file, "r", encoding="utf-8") as f:
            cached_result = f.read()
        with st.container(border=True):
            st.markdown(cached_result)

        if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="esr_rerun_ai"):
            os.remove(ai_cache_file)
            st.rerun()
    else:
        btn_label = f"🐺 Phân tích ESR Rủi ro Hệ thống ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True, key="esr_run_ai"):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang phân tích rủi ro hệ thống và phân rã PCA..."):
                    try:
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])

                        with open(str(ROOT_DIR / "promt" / "ESR monitor promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()

                        # Thu thập dữ liệu
                        date_str = df.index[-1].strftime('%d/%m/%Y')
                        index_close = last['INDEX_Close']
                        ma_col = f"MA{ma_period}"
                        ma_val = last.get(ma_col, 0)
                        ma_status = "nằm trên" if index_close >= ma_val else "nằm dưới"
                        ssi_pct = last['SSI_Index'] * 100
                        status = "SAFE" if last['SSI_Index'] < 0.5 else "WARNING" if last['SSI_Index'] < 0.8 else "CRITICAL"

                        # Top 3 PCA weights
                        sorted_w = weights.sort_values(ascending=False)
                        w1_name = sorted_w.index[0]
                        w1_val = sorted_w.iloc[0] * 100
                        w2_name = sorted_w.index[1]
                        w2_val = sorted_w.iloc[1] * 100
                        w3_name = sorted_w.index[2]
                        w3_val = sorted_w.iloc[2] * 100

                        # Replace placeholders
                        full_prompt = prompt_template
                        full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
                        full_prompt = full_prompt.replace("[Nhập điểm số VN30]", f"{index_close:.2f}")
                        full_prompt = full_prompt.replace("[nằm trên/nằm dưới]", ma_status)
                        full_prompt = full_prompt.replace("[20/60/125/252]", str(ma_period))
                        full_prompt = full_prompt.replace("[Nhập %, VD: 85.5%]", f"{ssi_pct:.1f}%")
                        full_prompt = full_prompt.replace("[SAFE / WARNING / CRITICAL]", status)
                        full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w1_name} ({w1_val:.0f}%)", 1)
                        full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w2_name} ({w2_val:.0f}%)", 1)
                        full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w3_name} ({w3_val:.0f}%)", 1)

                        parts = full_prompt.split("# INPUT DATA")
                        system_prompt = parts[0].strip()
                        user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

                        response = client.chat.completions.create(
                            model=cfg["api_model"],
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=AI_TEMPERATURE
                        )

                        result_text = response.choices[0].message.content

                        # Lưu cache
                        ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(ai_cache_file, "w", encoding="utf-8") as f:
                            f.write(result_text)

                        st.success("Hoàn thành phân tích!")
                        with st.container(border=True):
                            st.markdown(result_text)

                    except Exception as e:
                        st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại cấu hình thư viện openai và API key!")
