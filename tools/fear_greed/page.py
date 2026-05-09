"""
tools/fear_greed/page.py
Hàm render() được gọi bởi pages/1_Fear_Greed.py.
Đây là layer duy nhất biết cả Streamlit lẫn quant — kết nối 2 thế giới.
"""
import logging
import warnings
import streamlit as st

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from config                              import RANK_WINDOW, DEFAULT_WINDOW
from shared.data_loader                  import load_close_prices
from shared.daily_cache                  import load_daily_cache, save_daily_cache
from tools.fear_greed.quant.metrics      import calculate_quant_metrics
from tools.fear_greed.quant.scoring      import calculate_risk_score
from tools.fear_greed.ui.sidebar         import render_sidebar
from tools.fear_greed.ui.gauge           import render_gauge
from tools.fear_greed.ui.charts          import render_analysis_chart


@st.cache_data(show_spinner=False)
def _cached_metrics(df, window_size: int):
    return calculate_quant_metrics(df, window_size=window_size)


def render():
    st.title("🎯 Market Sentiment Monitor — PCA & EGARCH")
    st.caption(
        "Market Factor via PCA · EGARCH(1,1,1) Skewed-T · "
        "Rolling Percentile Rank · Kelly Skewness"
    )

    params      = render_sidebar()
    window_size = params["window_size"]

    # ── Tải dữ liệu từ hồ chứa ──────────────────────────────────────
    try:
        df_stocks = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_stocks.index.max().strftime('%d/%m/%Y')}")

    key = {"window_size": window_size}
    cached = load_daily_cache("fear_greed", key)
    if cached is not None:
        scored_df = cached["scored_df"]
        st.caption("⚡ Dùng cache cùng ngày (Fear & Greed).")
    else:
        with st.spinner("Đang chạy PCA + EGARCH pipeline..."):
            try:
                metrics_df = _cached_metrics(df_stocks, window_size)
            except RuntimeError as e:
                st.error(f"❌ Lỗi mô hình: {e}")
                st.stop()
        scored_df = calculate_risk_score(metrics_df, rank_window=RANK_WINDOW)
        save_daily_cache("fear_greed", key, {"scored_df": scored_df})
        st.caption("💾 Đã tạo cache ngày mới (Fear & Greed).")
    latest    = scored_df.iloc[-1]
    prev      = scored_df.iloc[-2]
    score     = latest["Risk_Score"]
    date_str  = scored_df.index[-1].strftime("%d/%m/%Y")

    # ── Hiển thị ────────────────────────────────────────────────────
    st.markdown(f"### 🚦 Fear & Greed Score — **{date_str}**")
    col_g, col_m = st.columns([1, 2])

    with col_g:
        render_gauge(score)

    with col_m:
        st.markdown("#### 🔍 Core Metrics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vol Rank (1Y)",      f"{latest['Vol_Norm']:.0%}",
                  f"{latest['Vol_Norm']-prev['Vol_Norm']:+.1%}",       delta_color="inverse")
        c2.metric("Kelly Skewness",     f"{latest['Skewness']:.2f}",
                  f"{latest['Skewness']-prev['Skewness']:+.2f}")
        c3.metric("Downside Corr Rank", f"{latest['Down_Corr_Norm']:.0%}",
                  f"{latest['Down_Corr_Norm']-prev['Down_Corr_Norm']:+.1%}", delta_color="inverse")
        c4.metric("Upside Corr Rank",   f"{latest['Up_Corr_Norm']:.0%}",
                  f"{latest['Up_Corr_Norm']-prev['Up_Corr_Norm']:+.1%}")

        st.info(
            "**Ghi chú kỹ thuật** \n"
            "- **Market Factor**: PCA — loại bỏ bias vốn hóa. \n"
            "- **Volatility**: EGARCH(1,1,1) Skewed-T — leverage effect & fat tails. \n"
            "- **Scaling**: Rolling percentile rank 252 ngày — robust với outlier. \n"
            "- **Skewness**: Kelly non-parametric, bounded [−1, 1]."
        )

    st.divider()
    st.subheader("✨ Trợ lý AI Quant Đánh giá Tâm lý Thị trường")

    import os
    from config import DATA_LAKE, AI_MODEL, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    
    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"feargreed_{today_str}.txt"
    
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
        if st.button("🐺 Phân tích Rủi ro Hệ thống (Moonshot AI v1 128k)", type="primary", use_container_width=True):
            if not params.get("kimi_key"):
                st.error("⚠️ Bạn chưa nhập Kimi API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang tổng hợp và phân tích dữ liệu rủi ro hệ thống..."):
                    try:
                        from openai import OpenAI
                        client = OpenAI(
                            api_key=params["kimi_key"].strip(),
                            base_url="https://api.moonshot.ai/v1"
                        )
                        
                        with open(str(ROOT_DIR / "promt" / "fear greed promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()
    
                        status_text = "EXTREME FEAR" if score <= 20 else "FEAR" if score <= 40 else "NEUTRAL / STOCK PICKING" if score < 60 else "GREED" if score < 80 else "EXTREME GREED"
    
                        full_prompt = prompt_template.replace("{date_str}", date_str)\
                                                     .replace("{score}", f"{score:.1f}")\
                                                     .replace("{score_delta}", f"{score - prev['Risk_Score']:+.1f}")\
                                                     .replace("{status_text}", status_text)\
                                                     .replace("{egarch_vol}", f"{latest['Vol_Norm']*100:.1f}")\
                                                     .replace("{egarch_delta}", f"{(latest['Vol_Norm'] - prev['Vol_Norm'])*100:+.1f}")\
                                                     .replace("{skewness}", f"{latest['Skewness']:.2f}")\
                                                     .replace("{down_corr}", f"{latest['Down_Corr_Norm']*100:.1f}")\
                                                     .replace("{up_corr}", f"{latest['Up_Corr_Norm']*100:.1f}")
                                                     
                        parts = full_prompt.split("# INPUT DATA")
                        system_prompt = parts[0].strip()
                        user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
                        response = client.chat.completions.create(
                            model=AI_MODEL,
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
                        st.error(f"Lỗi kết nối API Kimi: {e}. Vui lòng kiểm tra lại cấu hình thư viện openai và API key!")

    st.markdown("### 📈 Phân tích Định lượng")
    render_analysis_chart(scored_df)
