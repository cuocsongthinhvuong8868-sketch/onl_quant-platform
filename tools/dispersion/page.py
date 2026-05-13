import streamlit as st
import pandas as pd
from datetime import date
from config import DATA_LAKE, ROOT_DIR, AI_TEMPERATURE
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
from shared.data_loader import load_close_prices, load_custom
from tools.dispersion.quant.metrics import calculate_dispersion_metrics, fit_rolling_correlation
from tools.dispersion.ui.sidebar import render_sidebar
from tools.dispersion.ui.charts import render_main_chart


def _cache_path(params: dict) -> str:
    key = (
        f"mc{params['mc_window']}_rf{params['cov_refit_freq']}_"
        f"zt{params['zscore_type']}_z{params['zscore_window']}_"
        f"dpi{params['dpi_window']}"
    ).replace(".", "p")
    return str(DATA_LAKE / "daily_cache" / f"dispersion_cache_{key}.csv")


def _load_daily_cache(path: str):
    try:
        df = pd.read_csv(path, parse_dates=["time"])
    except Exception:
        return None
    if df.empty or "cache_date" not in df.columns:
        return None
    cache_day = str(df["cache_date"].iloc[0])
    if cache_day != str(date.today()):
        return None
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    return df


def _save_daily_cache(path: str, df_metrics: pd.DataFrame):
    cache_dir = (DATA_LAKE / "daily_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = df_metrics.copy()
    out = out.reset_index().rename(columns={"index": "time"})
    out["cache_date"] = str(date.today())
    out.to_csv(path, index=False)


@st.cache_data(show_spinner=False, ttl=86400)
def _compute_metrics_cached(df_prices, index_series, p: dict):
    stock_returns, metrics = calculate_dispersion_metrics(
        df_prices, index_series, p["zscore_type"], p["zscore_window"], p["dpi_window"]
    )
    corr = fit_rolling_correlation(
        stock_returns,
        window=p["mc_window"],
        refit_every=p["cov_refit_freq"],
    )
    metrics["Ledoit_Correlation"] = corr
    return metrics.dropna(subset=["DPI", "Ledoit_Correlation"])


def render():
    st.title("Macro Dispersion Radar")
    st.caption("Pure observation tool: Dispersion Persistence Index (DPI) & Systemic Correlation")

    p = render_sidebar()
    ai_provider = p["ai_provider"]
    api_key     = p["api_key"]
    if p["cov_refit_freq"] <= 1:
        st.warning("Thiết lập `refit Cov = 1` rất nặng với universe lớn. Nên dùng >= 3 để tăng tốc.")

    try:
        df_prices = load_close_prices()
        df_idx = load_custom("vnindex_cache.csv")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_prices.index.max().strftime('%d/%m/%Y')}")

    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    index_series = df_idx[idx_col]
    cache_file = _cache_path(p)

    metrics = _load_daily_cache(cache_file)
    if metrics is not None:
        st.caption(f"⚡ Dùng cache cùng ngày: {cache_file}")
    else:
        with st.spinner("Đang tính Dispersion metrics..."):
            metrics = _compute_metrics_cached(df_prices, index_series, p)
            try:
                _save_daily_cache(cache_file, metrics)
                st.caption(f"💾 Đã tạo cache ngày mới: {cache_file}")
            except Exception as e:
                st.warning(f"Tính xong nhưng không ghi được cache file: {e}")

    if metrics.empty:
        st.warning("Không đủ dữ liệu để tạo tín hiệu dispersion.")
        return

    latest = metrics.iloc[-1]
    
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Spread_Z ({p['zscore_type']})", f"{latest['Spread_Z']:+.2f}σ")
    c2.metric(f"DPI ({p['dpi_window']}d)", f"{latest['DPI']:.1f}%")
    c3.metric("Ledoit Corr", f"{latest['Ledoit_Correlation']:.3f}")

    render_main_chart(
        metrics,
        recent_window_2d=p["recent_window_2d"]
    )

    st.divider()
    st.subheader("✨ Trợ lý AI Quant Phân tích Dispersion")

    import os
    from datetime import date
    
    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"dispersion_{ai_provider}_{today_str}.txt"
    
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
        btn_label = f"🐺 Chẩn đoán Cấu trúc & Đứt gãy ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang phân tích cấu trúc rủi ro phân tán..."):
                    try:
                        from openai import OpenAI
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
    
                        with open(str(ROOT_DIR / "promt" / "dispersion promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()
    
                        date_str = metrics.index.max().strftime('%d/%m/%Y')
                        
                        spread_val = latest.get("Spread", 0) * 100 * (252**0.5)
                        spread_z = latest.get("Spread_Z", 0)
                        dpi_val = latest.get("DPI", 0)
                        
                        corr_val = latest.get("Ledoit_Correlation", 0)
                        
                        cs_skew = latest.get("CS_Skewness", "N/A")
                        if isinstance(cs_skew, (int, float)) and not pd.isna(cs_skew): cs_skew = f"{cs_skew:+.2f}"
                        cs_kurt = latest.get("CS_Kurtosis", "N/A")
                        if isinstance(cs_kurt, (int, float)) and not pd.isna(cs_kurt): cs_kurt = f"{cs_kurt:.2f}"
    
                        full_prompt = prompt_template.replace("{date_str}", date_str)\
                                                     .replace("{spread_val}", f"{spread_val:.2f}")\
                                                     .replace("{spread_z}", f"{spread_z:+.2f}")\
                                                     .replace("{dpi_val}", f"{dpi_val:.1f}")\
                                                     .replace("{corr_val}", f"{corr_val:.3f}")\
                                                     .replace("{cs_skew}", cs_skew)\
                                                     .replace("{cs_kurt}", cs_kurt)

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

