import streamlit as st
import pandas as pd
import os
from shared.data_loader import load_custom
from tools.var_cvar_vnindex.quant.metrics import METHOD_VERSION, calculate_var_cvar_metrics, summarize_var_cvar_state
from tools.var_cvar_vnindex.quant.evt import evt_posterior_intervals, evt_threshold_sensitivity
from tools.var_cvar_vnindex.ui.sidebar import render_sidebar
from tools.var_cvar_vnindex.ui.charts import plot_var_cvar, plot_evt_tail_risk

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"},
        "kimi-2.6-local": {"display": "Kimi 2.6 Local", "api_model": "kimi-k2.6", "base_url": "http://127.0.0.1:5001/v1"},
        "chatgpt-local": {"display": "ChatGPT Local", "api_model": "gpt-5.5", "base_url": "http://127.0.0.1:5003/v1"},
    }


def _evt_xi_label(xi_val):
    return "Light" if xi_val < 0.05 else ("Heavy" if xi_val < 0.30 else "Fat Tail")


def _evt_xi_prompt_value(xi_val, intervals):
    xi_text = f"{xi_val:+.3f} MLE ({_evt_xi_label(xi_val)})"
    if intervals and intervals.get("status") == "ok":
        xi = intervals.get("xi", {})
        xi_text += (
            f"; MCMC posterior p50 {xi.get('p50', 0.0):+.3f}, "
            f"90% CI [{xi.get('p05', 0.0):+.3f}, {xi.get('p95', 0.0):+.3f}]"
        )
    return xi_text


def show():
    st.title("Var-CVaR(ES) VNINDEX")
    st.caption("Phân tích rủi ro đuôi VNINDEX: Parametric VaR, Historical VaR & Expected Shortfall (ES).")

    plot_start_date = render_sidebar()

    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="var_cvar_ai_provider",
    )
    api_key_raw = st.sidebar.text_input("API Key (hoặc shortcut 4 số):", type="password", key="var_cvar_api_key",
        placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
    from shared.api_key_helper import resolve_api_key
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    # ── Load VNINDEX ──
    try:
        df_vni = load_custom("vnindex_cache.csv")
        idx_col = "VNINDEX" if "VNINDEX" in df_vni.columns else df_vni.columns[0]
        vni_series = df_vni[idx_col]
        data_date_raw = vni_series.dropna().index.max()
        data_date_token = data_date_raw.strftime("%d%m%y") if hasattr(data_date_raw, "strftime") else pd.Timestamp.today().strftime("%d%m%y")
        st.caption(f"Method: {METHOD_VERSION} · Data date: {data_date_raw} · VaR/ES dùng prior-window returns")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    # ── Tính toán ──
    if st.button("🔍 Tính toán VaR & CVaR VNINDEX", type="primary", use_container_width=True, key="var_cvar_run"):
        with st.spinner("Đang tính toán VaR, CVaR & ES cho VNINDEX..."):
            df_metrics = calculate_var_cvar_metrics(vni_series)
            st.session_state.var_cvar_metrics = df_metrics
            st.session_state.var_cvar_evt_sensitivity = evt_threshold_sensitivity(
                df_metrics["return_for_risk_model"]
            )
            st.session_state.var_cvar_evt_intervals = evt_posterior_intervals(
                df_metrics["return_for_risk_model"]
            )

    # ── Hiển thị ──
    if "var_cvar_metrics" in st.session_state:
        df_metrics = st.session_state.var_cvar_metrics
        df_plot = df_metrics[df_metrics.index >= pd.to_datetime(plot_start_date)].dropna(
            subset=["parametric_var", "historical_var", "expected_shortfall"]
        )

        if not df_plot.empty:
            tab_classic, tab_evt = st.tabs([
                "📊 VaR/CVaR Classic (95%)",
                "🔥 EVT Tail Risk (POT-GPD, quantile cực đoan)",
            ])
            with tab_classic:
                fig = plot_var_cvar(df_plot)
                st.plotly_chart(fig, use_container_width=True)
            with tab_evt:
                if 'evt_var_99' in df_plot.columns and df_plot['evt_var_99'].notna().any():
                    fig_evt = plot_evt_tail_risk(df_plot)
                    st.plotly_chart(fig_evt, use_container_width=True)
                    st.caption(
                        "📌 **POT-GPD** (Peaks-Over-Threshold + Generalized Pareto Distribution): "
                        "fit phân phối chỉ vào top 10% losses → extrapolate VaR/ES tới quantile 99%, 99.5%, 99.9% "
                        "với độ tin cậy cao hơn Gaussian. ξ (xi) > 0.15 báo hiệu **heavy tail**; > 0.30 = **fat tail**."
                    )
                    sensitivity = st.session_state.get("var_cvar_evt_sensitivity")
                    if sensitivity is None:
                        sensitivity = evt_threshold_sensitivity(df_metrics["return_for_risk_model"])
                        st.session_state.var_cvar_evt_sensitivity = sensitivity

                    with st.expander("🧪 EVT threshold sensitivity", expanded=True):
                        valid_sensitivity = sensitivity[sensitivity["status"] == "ok"].copy()
                        if valid_sensitivity.empty:
                            st.warning("Không đủ exceedances để chạy threshold sensitivity.")
                        else:
                            display_columns = [
                                "threshold_pct", "n_exceed", "xi",
                                "evt_var_99", "evt_es_99",
                                "evt_var_995", "evt_es_995",
                            ]
                            display = valid_sensitivity[display_columns].copy()
                            display["threshold_pct"] *= 100
                            for col in ["evt_var_99", "evt_es_99", "evt_var_995", "evt_es_995"]:
                                display[col] *= 100
                            st.dataframe(
                                display.rename(columns={
                                    "threshold_pct": "Tail sample (%)",
                                    "n_exceed": "# Exceed",
                                    "xi": "ξ",
                                    "evt_var_99": "VaR 99 (%)",
                                    "evt_es_99": "ES 99 (%)",
                                    "evt_var_995": "VaR 99.5 (%)",
                                    "evt_es_995": "ES 99.5 (%)",
                                }).style.format({
                                    "Tail sample (%)": "{:.1f}",
                                    "ξ": "{:+.3f}",
                                    "VaR 99 (%)": "{:.2f}",
                                    "ES 99 (%)": "{:.2f}",
                                    "VaR 99.5 (%)": "{:.2f}",
                                    "ES 99.5 (%)": "{:.2f}",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )
                            xi_range = valid_sensitivity["xi"].max() - valid_sensitivity["xi"].min()
                            var99_range = (
                                valid_sensitivity["evt_var_99"].max()
                                - valid_sensitivity["evt_var_99"].min()
                            )
                            es99_range = (
                                valid_sensitivity["evt_es_99"].max()
                                - valid_sensitivity["evt_es_99"].min()
                            )
                            st.caption(
                                f"Độ nhạy trên tail sample 5%-15%: "
                                f"Δξ={xi_range:.3f}, "
                                f"range VaR99={abs(var99_range)*100:.2f} điểm %, "
                                f"range ES99={abs(es99_range)*100:.2f} điểm %. "
                                "Range lớn cho thấy kết quả phụ thuộc mạnh vào threshold và cần thận trọng."
                            )
                    intervals = st.session_state.get("var_cvar_evt_intervals")
                    if intervals is None:
                        intervals = evt_posterior_intervals(df_metrics["return_for_risk_model"])
                        st.session_state.var_cvar_evt_intervals = intervals
                    with st.expander("EVT MCMC posterior interval", expanded=False):
                        if intervals.get("status") != "ok":
                            st.warning("Không đủ dữ liệu để chạy MCMC interval.")
                        else:
                            interval_rows = [
                                {"metric": "xi", **intervals["xi"]},
                                {
                                    "metric": "EVT VaR99 (%)",
                                    "p05": intervals["evt_var_99"]["p05"] * 100,
                                    "p50": intervals["evt_var_99"]["p50"] * 100,
                                    "p95": intervals["evt_var_99"]["p95"] * 100,
                                },
                                {
                                    "metric": "EVT ES99 (%)",
                                    "p05": intervals["evt_es_99"]["p05"] * 100,
                                    "p50": intervals["evt_es_99"]["p50"] * 100,
                                    "p95": intervals["evt_es_99"]["p95"] * 100,
                                },
                            ]
                            st.caption(
                                f"Method={intervals.get('method')} | "
                                f"acceptance={intervals.get('acceptance_rate', 0):.1%} | "
                                f"samples={intervals.get('posterior_samples', 0)}"
                            )
                            st.dataframe(
                                pd.DataFrame(interval_rows).style.format({
                                    "p05": "{:+.3f}",
                                    "p50": "{:+.3f}",
                                    "p95": "{:+.3f}",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )
                else:
                    st.info("ℹ️ EVT cần ≥ 3 năm data (756 phiên). Quay lại sau khi backfill xong.")
        else:
            st.warning("Không có dữ liệu trong khoảng thờ gian đã chọn.")

        # Metrics T0
        latest = df_metrics.dropna(subset=["historical_var"]).iloc[-1]
        latest_date = df_metrics.dropna(subset=["historical_var"]).index[-1]
        sensitivity_for_summary = st.session_state.get("var_cvar_evt_sensitivity")
        intervals_for_summary = st.session_state.get("var_cvar_evt_intervals")
        tail_summary = summarize_var_cvar_state(
            latest,
            sensitivity=sensitivity_for_summary,
            intervals=intervals_for_summary,
        )

        st.markdown("### 📈 Snapshot T0")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Giá VNINDEX", f"{latest['price']:,.2f}")
        with col2:
            st.metric("σ 30 ngày", f"{latest['stdev_30']*100:.2f}%")
        with col3:
            st.metric("Parametric VaR 95%", f"{latest['parametric_var']*100:.2f}%",
                      help="Gaussian: μ₃₀ + z₀.₀₅·σ₃₀. Đánh giá thấp tail risk khi có fat tail.")
        with col4:
            st.metric("Historical VaR 95%", f"{latest['historical_var']*100:.2f}%",
                      help="Rolling 5th percentile, 3-year window. Empirical.")

        col5, col6 = st.columns(2)
        with col5:
            st.metric("Expected Shortfall 95%", f"{latest['expected_shortfall']*100:.2f}%")
        with col6:
            es_exceed = latest['es_var_spread']
            st.metric("ES - VaR Spread", f"{es_exceed*100:.2f}%",
                      delta="Tail risk" if es_exceed < 0 else "")

        col7, col8, col9, col10 = st.columns(4)
        with col7:
            st.metric("Return T0", f"{latest['return']*100:.2f}%")
        with col8:
            st.metric(
                "VaR Breach 95%",
                "YES" if bool(latest["var_breach_95"]) else "NO",
                delta=f"{latest['breach_margin_95']*100:.2f}pp" if bool(latest["var_breach_95"]) else None,
            )
        with col9:
            st.metric("Tail Regime", tail_summary["tail_regime"])
        with col10:
            gap = latest.get("evt_gaussian_var99_gap", pd.NA)
            st.metric("EVT - Gaussian VaR99", f"{gap*100:.2f}pp" if pd.notna(gap) else "N/A")

        # ── EVT metrics (nếu có) ──
        has_evt = 'evt_var_99' in df_metrics.columns and pd.notna(latest.get('evt_var_99'))
        if has_evt:
            st.markdown("### 🔥 EVT — Tail Risk Extreme Quantiles")
            ce1, ce2, ce3, ce4 = st.columns(4)
            with ce1:
                st.metric("EVT VaR 99%", f"{latest['evt_var_99']*100:.2f}%",
                          help="POT-GPD extrapolation. Chính xác hơn Gaussian ở quantile cực đoan.")
            with ce2:
                st.metric("EVT VaR 99.5%", f"{latest['evt_var_995']*100:.2f}%",
                          help="Sự kiện 1 năm xảy ra ~1 lần (1/200 phiên).")
            with ce3:
                st.metric("EVT ES 99%", f"{latest['evt_es_99']*100:.2f}%",
                          help="Mức tổn thất trung bình kỳ vọng KHI vượt quá VaR 99%.")
            with ce4:
                es_var_99_spread = latest['evt_es_99'] - latest['evt_var_99']
                st.metric("EVT ES-VaR Spread 99%", f"{es_var_99_spread*100:.2f}%",
                          help="Spread càng âm = tail càng nặng.")

            ce5, ce6, ce7, ce8 = st.columns(4)
            with ce5:
                xi_val = float(latest['evt_xi'])
                xi_label = _evt_xi_label(xi_val)
                st.metric("xi MLE (GPD shape)", f"{xi_val:+.3f}",
                          delta=xi_label,
                          delta_color="off" if xi_val < 0.15 else "inverse",
                          help="MLE point estimate. xi>0.15=heavy; xi>0.30=fat tail.")
            with ce6:
                hill_val = latest['hill_index']
                st.metric("Hill index", f"{hill_val:+.3f}",
                          help="Hill (1975) tail estimator. Cross-check cho ξ; cùng dấu = robust signal.")
            with ce7:
                st.metric("Threshold u", f"{latest['evt_threshold']*100:.2f}%",
                          help="Loss-scale threshold cho POT. Top 10% losses là exceedances.")
            with ce8:
                st.metric("# Exceedances", f"{int(latest['evt_n_exceed'])}",
                          help="Số phiên loss vượt threshold trong window 3 năm.")

            interval_snapshot = st.session_state.get("var_cvar_evt_intervals")
            if interval_snapshot and interval_snapshot.get("status") == "ok":
                xi_interval = interval_snapshot.get("xi", {})
                st.caption(
                    f"MCMC posterior xi: p50={xi_interval.get('p50', 0.0):+.3f}, "
                    f"90% CI=[{xi_interval.get('p05', 0.0):+.3f}, "
                    f"{xi_interval.get('p95', 0.0):+.3f}]. "
                    "The metric above remains the MLE point estimate used by legacy scoring."
                )

            # Diagnostic so sánh Gaussian vs EVT
            gauss_99 = latest['mean_30'] + (-2.3263) * latest['stdev_30']  # z_99
            underestimate = (latest['evt_var_99'] - gauss_99) * 100
            st.info(
                f"💡 **Diagnostic:** Gaussian VaR 99% (μ₃₀ + z₀.₀₁·σ₃₀) ≈ {gauss_99*100:.2f}% — "
                f"EVT cho {latest['evt_var_99']*100:.2f}%. Gaussian đang **{'underestimate' if underestimate < 0 else 'overestimate'} "
                f"tail risk {abs(underestimate):.2f} điểm phần trăm**. xi MLE={xi_val:+.3f} → "
                f"{'phân phối có đuôi dày, mô hình Gaussian không phù hợp.' if xi_val > 0.15 else 'phân phối khá gần Gaussian.'}"
            )

        # ── AI Analysis ──
        st.divider()
        st.subheader("✨ Trợ lý AI Phân tích VaR-CVaR VNINDEX")

        from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
        from openai import OpenAI

        ai_cache_file = DATA_LAKE / "daily_cache" / f"var_cvar_vnindex_{ai_provider}_{data_date_token}.txt"

        tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])
        with tab_current:
            if ai_cache_file.exists():
                st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
                with open(ai_cache_file, "r", encoding="utf-8") as f:
                    cached_result = f.read()
                with st.container(border=True):
                    st.markdown(cached_result)

                from shared.github_sync import render_sync_button
                render_sync_button(ai_cache_file, key_suffix="var_cvar")

                if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="var_cvar_rerun_ai"):
                    os.remove(ai_cache_file)
                    st.rerun()
            else:
                btn_label = f"🐺 Phân tích VaR-CVaR ({AI_PROVIDER_MAP[ai_provider]['display']})"
                if st.button(btn_label, type="primary", use_container_width=True, key="var_cvar_run_ai"):
                    if not api_key:
                        st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                    else:
                        with st.spinner("AI đang phân tích rủi ro đuôi VNINDEX..."):
                            try:
                                cfg = AI_PROVIDER_MAP[ai_provider]
                                client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))

                                with open(str(ROOT_DIR / "promt" / "var_cvar_vnindex_promt.md"), "r", encoding="utf-8") as f:
                                    prompt_template = f.read()

                                date_str = latest_date.strftime('%d/%m/%Y')
                                full_prompt = prompt_template
                                full_prompt = full_prompt.replace("[Nhập ngày]", date_str)
                                full_prompt = full_prompt.replace("[Giá VNINDEX]", f"{latest['price']:,.2f}")
                                full_prompt = full_prompt.replace("[σ 30 ngày]", f"{latest['stdev_30']*100:.2f}%")
                                full_prompt = full_prompt.replace("[Parametric VaR]", f"{latest['parametric_var']*100:.2f}%")
                                full_prompt = full_prompt.replace("[Historical VaR]", f"{latest['historical_var']*100:.2f}%")
                                full_prompt = full_prompt.replace("[Expected Shortfall]", f"{latest['expected_shortfall']*100:.2f}%")
                                full_prompt = full_prompt.replace("[ES - VaR Spread]", f"{(latest['expected_shortfall'] - latest['historical_var'])*100:.2f}%")
                                if has_evt:
                                    intervals = st.session_state.get("var_cvar_evt_intervals")
                                    full_prompt = full_prompt.replace("[EVT VaR 99%]", f"{latest['evt_var_99']*100:.2f}%")
                                    full_prompt = full_prompt.replace("[EVT VaR 99.5%]", f"{latest['evt_var_995']*100:.2f}%")
                                    full_prompt = full_prompt.replace("[EVT ES 99%]", f"{latest['evt_es_99']*100:.2f}%")
                                    full_prompt = full_prompt.replace("[EVT Xi]", _evt_xi_prompt_value(float(latest['evt_xi']), intervals))
                                    full_prompt = full_prompt.replace("[Hill Index]", f"{latest['hill_index']:+.3f}")
                                    full_prompt = full_prompt.replace("[EVT N Exceed]", str(int(latest['evt_n_exceed'])))

                                    sensitivity = st.session_state.get("var_cvar_evt_sensitivity")
                                    valid_sensitivity = (
                                        sensitivity[sensitivity["status"] == "ok"]
                                        if sensitivity is not None else pd.DataFrame()
                                    )
                                    if not valid_sensitivity.empty:
                                        xi_min = float(valid_sensitivity["xi"].min())
                                        xi_max = float(valid_sensitivity["xi"].max())
                                        xi_range = xi_max - xi_min
                                        var99_range = float(valid_sensitivity["evt_var_99"].max() - valid_sensitivity["evt_var_99"].min())
                                        es99_range = float(valid_sensitivity["evt_es_99"].max() - valid_sensitivity["evt_es_99"].min())
                                        stable_flag = int(xi_range <= 0.10 and abs(var99_range) <= 0.01 and abs(es99_range) <= 0.015)
                                        full_prompt = full_prompt.replace("[EVT Xi Min]", f"{xi_min:+.3f}")
                                        full_prompt = full_prompt.replace("[EVT Xi Max]", f"{xi_max:+.3f}")
                                        full_prompt = full_prompt.replace("[EVT Xi Range]", f"{xi_range:.3f}")
                                        full_prompt = full_prompt.replace("[EVT VaR99 Range]", f"{abs(var99_range)*100:.2f}pp")
                                        full_prompt = full_prompt.replace("[EVT ES99 Range]", f"{abs(es99_range)*100:.2f}pp")
                                        full_prompt = full_prompt.replace("[EVT Threshold Stable]", str(stable_flag))
                                        full_prompt = full_prompt.replace("[EVT Sensitivity Status]", "stable" if stable_flag else "threshold_sensitive")

                                    if intervals and intervals.get("status") == "ok":
                                        full_prompt = full_prompt.replace("[EVT Interval Method]", str(intervals.get("method", "gpd_random_walk_mcmc")))
                                        full_prompt = full_prompt.replace("[EVT MCMC Acceptance]", f"{intervals.get('acceptance_rate', 0):.1%}")
                                        full_prompt = full_prompt.replace("[EVT MCMC Samples]", str(intervals.get("posterior_samples", 0)))
                                        full_prompt = full_prompt.replace("[EVT Xi P05]", f"{intervals['xi']['p05']:+.3f}")
                                        full_prompt = full_prompt.replace("[EVT Xi P50]", f"{intervals['xi']['p50']:+.3f}")
                                        full_prompt = full_prompt.replace("[EVT Xi P95]", f"{intervals['xi']['p95']:+.3f}")
                                        full_prompt = full_prompt.replace("[EVT VaR99 P05]", f"{intervals['evt_var_99']['p05']*100:.2f}%")
                                        full_prompt = full_prompt.replace("[EVT VaR99 P50]", f"{intervals['evt_var_99']['p50']*100:.2f}%")
                                        full_prompt = full_prompt.replace("[EVT VaR99 P95]", f"{intervals['evt_var_99']['p95']*100:.2f}%")
                                        full_prompt = full_prompt.replace("[EVT ES99 P05]", f"{intervals['evt_es_99']['p05']*100:.2f}%")
                                        full_prompt = full_prompt.replace("[EVT ES99 P50]", f"{intervals['evt_es_99']['p50']*100:.2f}%")
                                        full_prompt = full_prompt.replace("[EVT ES99 P95]", f"{intervals['evt_es_99']['p95']*100:.2f}%")

                                for placeholder in [
                                    "[EVT VaR 99%]", "[EVT VaR 99.5%]", "[EVT ES 99%]",
                                    "[EVT Xi]", "[Hill Index]", "[EVT N Exceed]",
                                    "[EVT Xi Min]", "[EVT Xi Max]", "[EVT Xi Range]",
                                    "[EVT VaR99 Range]", "[EVT ES99 Range]",
                                    "[EVT Threshold Stable]", "[EVT Sensitivity Status]",
                                    "[EVT Interval Method]", "[EVT MCMC Acceptance]", "[EVT MCMC Samples]",
                                    "[EVT Xi P05]", "[EVT Xi P50]", "[EVT Xi P95]",
                                    "[EVT VaR99 P05]", "[EVT VaR99 P50]", "[EVT VaR99 P95]",
                                    "[EVT ES99 P05]", "[EVT ES99 P50]", "[EVT ES99 P95]",
                                ]:
                                    full_prompt = full_prompt.replace(placeholder, "N/A")
                                full_prompt += (
                                    "\n\n# V3 DIAGNOSTICS\n"
                                    f"- Methodology: {METHOD_VERSION}\n"
                                    f"- Tail regime: {tail_summary['tail_regime']} ({tail_summary['tail_risk_level']})\n"
                                    f"- Current log return: {latest['return']*100:.2f}%\n"
                                    f"- VaR breach 95%: {int(bool(latest['var_breach_95']))}; breach margin: {latest['breach_margin_95']*100:.2f}pp\n"
                                    f"- Gaussian VaR99: {latest['gaussian_var_99']*100:.2f}%; EVT VaR99 gap: {latest.get('evt_gaussian_var99_gap', 0.0)*100:.2f}pp\n"
                                    f"- EVT threshold stable: {int(tail_summary['evt_threshold_stable'])}; xi range: {tail_summary['evt_sensitivity_xi_range']:.3f}\n"
                                    "- Method control: same-date VaR/ES uses prior-window returns only; no forward-fill; bad ticks abs(simple return)>50% removed.\n"
                                )

                                parts = full_prompt.split("# INPUT DATA")
                                system_prompt = parts[0].strip()
                                user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

                                response = client.chat.completions.create(
                                    model=cfg["api_model"],
                                    messages=[
                                        {"role": "system", "content": system_prompt},
                                        {"role": "user", "content": user_prompt}
                                    ],
                                    temperature=AI_PROVIDER_MAP[ai_provider].get("temperature", AI_TEMPERATURE)
                                )
                                result_text = response.choices[0].message.content

                                ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                                with open(ai_cache_file, "w", encoding="utf-8") as f:
                                    f.write(result_text)

                                st.success("Hoàn thành phân tích!")
                                with st.container(border=True):
                                    st.markdown(result_text)

                            except Exception as e:
                                st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại!")

        with tab_history:
            from shared.history_selector import build_history_options
            _all_caches = list(DATA_LAKE.glob("daily_cache/var_cvar_vnindex_*.txt"))
            _options = build_history_options(_all_caches, "var_cvar_vnindex", AI_PROVIDER_MAP)
            if not _options:
                st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
            else:
                _selected_label = st.selectbox(
                    "📅 Chọn ngày và model:",
                    options=list(_options.keys()),
                    index=0,
                    key="var_cvar_vnindex_history_selector"
                )
                _sel_path = _options[_selected_label]
                with st.container(border=True):
                    try:
                        with open(_sel_path, "r", encoding="utf-8") as f:
                            st.markdown(f.read())
                    except Exception as e:
                        st.error(f"Lỗi đọc file: {e}")
