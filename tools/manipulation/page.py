"""
tools/manipulation/page.py
Hàm render() được gọi bởi pages/tools_page_C/_8_Manipulation.py hoặc từ C_Behavioral_Finance.py
Phát hiện dấu hiệu thao túng/chỉ số qua PCA trên VIC/VHM/VRE vs VNINDEX
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
from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import clear_daily_cache, load_daily_cache, save_daily_cache
from shared.llm_policy import completion_options
from tools.manipulation.quant.engine import METHOD_VERSION, TARGET, prepare_data, compute_metrics, classify_regime
from tools.manipulation.ui.sidebar import render_sidebar
from tools.manipulation.ui.charts import render_core, render_event


def render():
    st.title("🔍 Manipulation Detection — VIC/VHM/VRE vs VNINDEX")
    st.caption(
        "PCA Composite · Rolling VaR/CVaR · Percentile Rank Correlation · "
        f"Event Study Regime Classification · {METHOD_VERSION}"
    )

    params = render_sidebar(default_threshold=0.15)
    window = params["window"]
    threshold = params["threshold"]
    ai_provider = params["ai_provider"]
    api_key = params["api_key"]

    try:
        df_prices = load_close_prices()
        df_idx = load_custom("vnindex_cache.csv")
        idx_col = TARGET if TARGET in df_idx.columns else df_idx.columns[0]
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    try:
        df_prepared = prepare_data(df_prices, target_series=df_idx[idx_col])
    except ValueError as e:
        st.error(f"❌ Lỗi dữ liệu: {e}")
        st.stop()

    raw_data_date = df_prices.index.max().strftime("%Y-%m-%d")
    effective_data_date = df_prepared.dropna().index.max().strftime("%Y-%m-%d")
    st.caption(
        f"📅 Dữ liệu cuối cùng: {pd.Timestamp(raw_data_date).strftime('%d/%m/%Y')} · "
        f"Manipulation input valid tới: {pd.Timestamp(effective_data_date).strftime('%d/%m/%Y')}"
    )

    key = {"method": METHOD_VERSION, "target": TARGET, "window": window}
    cached = load_daily_cache("manipulation", key, data_date=effective_data_date)
    if cached is not None:
        cached_result_date = cached["result"].index.max().strftime("%Y-%m-%d")
        if cached_result_date != effective_data_date:
            clear_daily_cache("manipulation", key)
            cached = None
            st.warning(
                f"Cache Manipulation stale ({cached_result_date}) so với input ({effective_data_date}); "
                "đang tính lại."
            )
    if cached is not None:
        weights = cached["weights"]
        result = cached["result"]
        st.caption(f"⚡ Dùng cache cùng ngày (Manipulation, result tới {result.index[-1].strftime('%d/%m/%Y')}).")
    else:
        with st.spinner("Đang chạy PCA + Rolling Metrics..."):
            try:
                weights, result = compute_metrics(df_prepared, window=window)
            except ValueError as e:
                st.error(f"❌ Lỗi dữ liệu: {e}")
                st.stop()
        save_daily_cache("manipulation", key, {"weights": weights, "result": result}, data_date=effective_data_date)
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
    from openai import OpenAI
    
    ai_cache_token = pd.Timestamp(effective_data_date).strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"manipulation_{ai_provider}_{ai_cache_token}.txt"
    
    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])
    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="manipulation")

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
                            client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))

                            with open(str(ROOT_DIR / "promt" / "manipulation promt.md"), "r", encoding="utf-8") as f:
                                prompt_template = f.read()

                            from scipy.stats import percentileofscore as _pctile

                            latest = result.iloc[-1]
                            date_str = result.index[-1].strftime('%d/%m/%Y')
                            corr_val = float(latest["Correlation"])
                            slope_val = float(latest["OLS_Slope"])

                            # Percentile full-history (khớp UI charts.py)
                            slope_pr = _pctile(result["OLS_Slope"].dropna(), slope_val, kind="rank")
                            corr_pr  = _pctile(result["Correlation"].dropna(), corr_val, kind="rank")
                            slope_status = "Cao" if slope_pr >= 80 else "Thap" if slope_pr <= 20 else "Trung binh"
                            corr_status  = "Rat chat" if corr_pr >= 80 else "Phan ky" if corr_pr <= 20 else "Long"

                            # Gia thuc te VIC/VHM/VRE + VNINDEX (chong AI hallucinate)
                            last_px = df_prepared.iloc[-1]
                            def _fmt_stk(v):
                                return f"{v:.2f} (≈ {int(v*1000):,} VND)" if (not __import__('math').isnan(v) and v > 0) else "N/A"
                            def _fmt_index(v):
                                return f"{v:,.2f} điểm" if (not __import__('math').isnan(v) and v > 0) else "N/A"
                            vic_close = _fmt_stk(float(last_px.get("VIC", float("nan"))))
                            vhm_close = _fmt_stk(float(last_px.get("VHM", float("nan"))))
                            vre_close = _fmt_stk(float(last_px.get("VRE", float("nan"))))
                            vnindex_close = _fmt_index(float(last_px.get(TARGET, float("nan"))))

                            # Event study: regime + momentum
                            t0_str = t0_dt.strftime('%d/%m/%Y')
                            if re_df is not None and not re_df.empty:
                                regime     = re_df["Regime"].iloc[-1]
                                d_corr     = re_df["Delta_PR_Corr"].iloc[-1]
                                d_slope    = re_df["Delta_PR_Slope"].iloc[-1]
                            else:
                                regime = "N/A"
                                d_corr = d_slope = 0.0
                            momentum_str = f"DeltaCorr = {d_corr:.2f}, DeltaSlope = {d_slope:.2f}"

                            full_prompt = prompt_template\
                                .replace("{date_str}",    date_str)\
                                .replace("{vic_close}",   vic_close)\
                                .replace("{vhm_close}",   vhm_close)\
                                .replace("{vre_close}",   vre_close)\
                                .replace("{vnindex_close}", vnindex_close)\
                                .replace("{slope_val}",   f"{slope_val:.3f}")\
                                .replace("{slope_pr}",    f"{slope_pr:.1f}")\
                                .replace("{slope_status}", slope_status)\
                                .replace("{corr_val}",    f"{corr_val:.3f}")\
                                .replace("{corr_pr}",     f"{corr_pr:.1f}")\
                                .replace("{corr_status}", corr_status)\
                                .replace("{t0_str}",      t0_str)\
                                .replace("{regime}",      regime)\
                                .replace("{momentum_str}", momentum_str)
                            full_prompt += (
                                "\n\n# V2 DIAGNOSTICS\n"
                                f"- Methodology: {METHOD_VERSION}\n"
                                f"- Target: {TARGET}, not VN30F1M.\n"
                                "- Interpretation: slope/correlation measure VIN composite coupling with cash VNINDEX, not futures trading signal.\n"
                                "- Return handling: pct_change(fill_method=None), log1p returns, rows require VIC/VHM/VRE/VNINDEX all valid.\n"
                            )

                            parts = full_prompt.split("# INPUT DATA")
                            system_prompt = parts[0].strip()
                            user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

                            response = client.chat.completions.create(
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ],
                                **completion_options(
                                    model=cfg["api_model"],
                                    route="child_report",
                                    temperature=AI_PROVIDER_MAP[ai_provider].get("temperature"),
                                ),
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

    with tab_history:
        from shared.history_selector import build_history_options
        _all_caches = list(DATA_LAKE.glob("daily_cache/manipulation_*.txt"))
        _options = build_history_options(_all_caches, "manipulation", AI_PROVIDER_MAP)
        if not _options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            _selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(_options.keys()),
                index=0,
                key="manipulation_history_selector"
            )
            _sel_path = _options[_selected_label]
            with st.container(border=True):
                try:
                    with open(_sel_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")
