"""
tools/manipulation/page.py
Hàm render() được gọi bởi pages/tools_page_C/_8_Manipulation.py hoặc từ C_Behavioral_Finance.py
Phát hiện dấu hiệu thao túng giá qua PCA trên VIC/VHM/VRE vs VN30F1M
"""
import logging
import warnings
import os
import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from config import AI_PROVIDER_MAP
from shared.data_loader import load_close_prices
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.manipulation.quant.engine import prepare_data, compute_metrics, classify_regime
from tools.manipulation.ui.sidebar import render_sidebar
from tools.manipulation.ui.charts import render_core, render_event


def render():
    st.title("🔍 Manipulation Detection — VIC/VHM/VRE vs VN30F1M")
    st.caption(
        "PCA Composite · Rolling VaR/CVaR · Percentile Rank Correlation · "
        "Event Study Regime Classification"
    )

    params = render_sidebar(default_threshold=0.15)
    window = params["window"]
    threshold = params["threshold"]
    ai_provider = params["ai_provider"]
    api_key = params["api_key"]

    try:
        df_prices = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_prices.index.max().strftime('%d/%m/%Y')}")

    key = {"window": window}
    cached = load_daily_cache("manipulation", key)
    if cached is not None:
        weights = cached["weights"]
        result = cached["result"]
        st.caption("⚡ Dùng cache cùng ngày (Manipulation).")
    else:
        with st.spinner("Đang chạy PCA + Rolling Metrics..."):
            try:
                df_prepared = prepare_data(df_prices)
                weights, result = compute_metrics(df_prepared, window=window)
            except ValueError as e:
                st.error(f"❌ Lỗi dữ liệu: {e}")
                st.stop()
        save_daily_cache("manipulation", key, {"weights": weights, "result": result})
        st.caption("💾 Đã tạo cache ngày mới (Manipulation).")

    # ── Hiển thị Core Metrics ──
    render_core(result, weights, result)

    # ── Event Study ──
    st.divider()
    st.subheader("📅 Even Study — Trạng thái hiện tại tính từ ngày T0")

    t0_default = result.index[-60] if len(result) >= 60 else result.index[0]
    t0_date = st.date_input("Chọn ngày gốc (t₀)", value=t0_default.date())
    t0_dt = pd.Timestamp(t0_date)

    re_df = classify_regime(result, threshold, t0_dt)
    render_event(re_df, threshold)

        # ── AI Analysis ──
    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Dấu hiệu Thao túng")

    from config import DATA_LAKE, ROOT_DIR
    from datetime import date
    from openai import OpenAI
    
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
        btn_label = f"🐺 Phân tích Thao túng ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang phân tích dấu hiệu thao túng..."):
                    try:
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
                        
                        with open(str(ROOT_DIR / "promt" / "manipulation promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()
    
                        latest = result.iloc[-1]
                        date_str = result.index[-1].strftime('%d/%m/%Y')
                        corr_val = float(latest["Correlation"])
                        slope_val = float(latest["OLS_Slope"])
                        var_val = float(latest["VaR_95"])
                        cvar_val = float(latest["CVaR_95"])
                        pr_corr = float(latest["PR_Corr"])
                        pr_slope = float(latest["PR_Slope"])

                        # Thống kê regime từ event study
                        if re_df is not None and not re_df.empty:
                            counts = re_df["Regime"].value_counts()
                            dominant = counts.idxmax()
                            coupling_pct = counts.get("COUPLING", 0) / len(re_df) * 100
                        else:
                            dominant = "N/A"
                            coupling_pct = 0

                        full_prompt = prompt_template.replace("{date_str}", date_str)\
                                                     .replace("{corr}", f"{corr_val:.3f}")\
                                                     .replace("{slope}", f"{slope_val:.3f}")\
                                                     .replace("{var_95}", f"{var_val*100:.2f}%")\
                                                     .replace("{cvar_95}", f"{cvar_val*100:.2f}%")\
                                                     .replace("{pr_corr}", f"{pr_corr:.2%}")\
                                                     .replace("{pr_slope}", f"{pr_slope:.2%}")\
                                                     .replace("{dominant_regime}", dominant)\
                                                     .replace("{coupling_pct}", f"{coupling_pct:.1f}%")
                                                     
                        parts = full_prompt.split("# INPUT DATA")
                        system_prompt = parts[0].strip()
                        user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
                        response = client.chat.completions.create(
                            model=cfg["api_model"],
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=AI_PROVIDER_MAP[ai_provider].get("temperature")
                        )
                        
                        result_text = response.choices[0].message.content
                        
                        # Lưu cache
                        ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(ai_cache_file, "w", encoding="utf-8") as f:
                            f.write(result_text)
                            
                        try:
                            from shared.github_sync import upload_file
                            import os as _os
                            if "GITHUB_TOKEN" in st.secrets or "GITHUB_TOKEN" in _os.environ:
                                repo_path = f"data_lake/daily_cache/{ai_cache_file.name}"
                                upload_file(repo_path, result_text.encode("utf-8"), f"Auto sync cache: {ai_cache_file.name}")
                        except Exception as e:
                            print(f"[GH Sync Error] {e}")
    
                        st.success("Hoàn thành phân tích!")
                        with st.container(border=True):
                            st.markdown(result_text)
    
                    except Exception as e:
                        st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại cấu hình thư viện openai và API key!")
