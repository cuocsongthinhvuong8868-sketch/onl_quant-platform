import streamlit as st
import pandas as pd

from shared.data_loader import load_close_prices
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.manipulation.quant.engine import prepare_data, compute_metrics, classify_regime
from tools.manipulation.ui.sidebar import render_sidebar
from tools.manipulation.ui.charts import render_core, render_event
try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {
            "display": "Kimi 2.6",
            "api_model": "kimi-k2.6",
            "base_url": "https://api.moonshot.ai/v1",
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }


def render():
    st.title("Manipulation Quant Radar")
    st.caption("Tác động VIC/VHM/VRE lên VN30F1M: PCA weights, risk band, event regime.")

    try:
        df_close = load_close_prices()
        df_prices = prepare_data(df_close)
    except Exception as e:
        st.error(f"Lỗi dữ liệu manipulation: {e}")
        st.stop()

    st.caption(f"📅 Dữ liệu cuối cùng: {df_prices.index.max().strftime('%d/%m/%Y')}")

    default_threshold = 0.15
    p = render_sidebar(default_threshold)
    ai_provider = p["ai_provider"]
    api_key     = p["api_key"]

    data_date = str(df_prices.index.max().date())
    key = {"cache_version": 1, "window": p["window"]}
    cached = load_daily_cache("manipulation", key, data_date=data_date)

    if cached is not None:
        weights_df = cached["weights_df"]
        result_df = cached["result_df"]
        st.caption("⚡ Dùng cache theo ngày dữ liệu (Manipulation).")
    else:
        with st.spinner("Đang tính manipulation metrics..."):
            try:
                weights_df, result_df = compute_metrics(df_prices, p["window"])
            except Exception as e:
                st.error(f"Lỗi tính toán manipulation: {e}")
                st.stop()
        save_daily_cache("manipulation", key, {"weights_df": weights_df, "result_df": result_df}, data_date=data_date)
        st.caption("💾 Đã tạo cache ngày mới (Manipulation).")

    if result_df.empty:
        st.warning("Không đủ dữ liệu sau warm-up.")
        return

    # date filter
    min_date, max_date = result_df.index.min().date(), result_df.index.max().date()
    date_selection = st.sidebar.date_input("Khoảng thời gian hiển thị", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    if len(date_selection) == 2:
        start_date, end_date = date_selection
    else:
        start_date, end_date = min_date, max_date

    mask_result = (result_df.index.date >= start_date) & (result_df.index.date <= end_date)
    plot_df = result_df.loc[mask_result]
    mask_weights = (weights_df.index.date >= start_date) & (weights_df.index.date <= end_date)
    plot_weights = weights_df.loc[mask_weights]

    render_core(plot_df, plot_weights, result_df)

    st.divider()
    st.subheader("4) Event Study 2D")
    available_dates = result_df.index.date
    target_t0 = pd.to_datetime("2026-03-02").date()
    default_t0 = target_t0 if len(available_dates) > 0 and available_dates[0] <= target_t0 <= available_dates[-1] else (available_dates[-min(60, len(available_dates)-1)] if len(available_dates) > 1 else available_dates[0])
    t0_date = st.date_input("Chọn ngày sự kiện t0", value=default_t0, min_value=available_dates[0], max_value=available_dates[-1])
    re_df = classify_regime(result_df, p["threshold"], pd.to_datetime(t0_date))
    render_event(re_df, p["threshold"])

    st.divider()
    st.subheader("✨ Trợ lý AI Quant Phân tích Tác động (Manipulation)")

    import os
    from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    
    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"manipulation_{ai_provider}_{today_str}.txt"
    
    if ai_cache_file.exists():
        st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
        with open(ai_cache_file, "r", encoding="utf-8") as f:
            cached_result = f.read()
        with st.container(border=True):
            st.markdown(cached_result)
            
        if st.button("🔄 Chạy lại phân tích AI", type="secondary"):
            os.remove(ai_cache_file)
            st.rerun()
    else:
        btn_label = f"🐺 Phân tích Dòng tiền & Tác động ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang tổng hợp và phân tích dữ liệu manipulation..."):
                    try:
                        from openai import OpenAI
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
    
                        with open(str(ROOT_DIR / "promt" / "manipulation promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()
    
                        date_str = result_df.index.max().strftime('%d/%m/%Y')
                        latest = result_df.iloc[-1]
    
                        slope_val = latest["OLS_Slope"]
                        slope_pr = latest["PR_Slope"] * 100
                        slope_status = "🔴 Cao" if slope_pr >= 80 else "🟢 Thấp" if slope_pr <= 20 else "🟡 Trung bình"
    
                        corr_val = latest["Correlation"]
                        corr_pr = latest["PR_Corr"] * 100
                        corr_status = "🔴 Rất chặt" if corr_pr >= 80 else "🟢 Phân kỳ" if corr_pr <= 20 else "🟡 Lỏng"
    
                        t0_str = pd.to_datetime(t0_date).strftime('%d/%m/%Y')
                        regime = re_df["Regime"].iloc[-1] if not re_df.empty else "N/A"
                        d_corr = re_df["Delta_PR_Corr"].iloc[-1] if not re_df.empty else 0
                        d_slope = re_df["Delta_PR_Slope"].iloc[-1] if not re_df.empty else 0
    
                        momentum_str = f"ΔCorr = {d_corr:.2f}, ΔSlope = {d_slope:.2f}"
    
                        full_prompt = prompt_template.replace("{date_str}", date_str)\
                                                     .replace("{slope_val}", f"{slope_val:.2f}")\
                                                     .replace("{slope_pr}", f"{slope_pr:.1f}")\
                                                     .replace("{slope_status}", slope_status)\
                                                     .replace("{corr_val}", f"{corr_val:.2f}")\
                                                     .replace("{corr_pr}", f"{corr_pr:.1f}")\
                                                     .replace("{corr_status}", corr_status)\
                                                     .replace("{t0_str}", t0_str)\
                                                     .replace("{regime}", regime)\
                                                     .replace("{momentum_str}", momentum_str)

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
