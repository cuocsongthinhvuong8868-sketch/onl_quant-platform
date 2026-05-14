import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import date
from shared.data_loader import load_custom
from tools.var_cvar_vnindex.quant.metrics import calculate_var_cvar_metrics
from tools.var_cvar_vnindex.ui.sidebar import render_sidebar
from tools.var_cvar_vnindex.ui.charts import plot_var_cvar

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"},
        "deepseek-v4-pro": {"display": "DeepSeek V4 Pro", "api_model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    }


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
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    # ── Load VNINDEX ──
    try:
        df_vni = load_custom("vnindex_cache.csv")
        idx_col = "VNINDEX" if "VNINDEX" in df_vni.columns else df_vni.columns[0]
        vni_series = df_vni[idx_col]
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    # ── Tính toán ──
    if st.button("🔍 Tính toán VaR & CVaR VNINDEX", type="primary", use_container_width=True, key="var_cvar_run"):
        with st.spinner("Đang tính toán VaR, CVaR & ES cho VNINDEX..."):
            df_metrics = calculate_var_cvar_metrics(vni_series)
            st.session_state.var_cvar_metrics = df_metrics

    # ── Hiển thị ──
    if "var_cvar_metrics" in st.session_state:
        df_metrics = st.session_state.var_cvar_metrics
        df_plot = df_metrics[df_metrics.index >= pd.to_datetime(plot_start_date)].dropna()

        if not df_plot.empty:
            fig = plot_var_cvar(df_plot)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Không có dữ liệu trong khoảng thờ gian đã chọn.")

        # Metrics T0
        latest = df_metrics.dropna().iloc[-1]
        latest_date = df_metrics.dropna().index[-1]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Giá VNINDEX", f"{latest['price']:,.2f}")
        with col2:
            st.metric("σ 30 ngày", f"{latest['stdev_30']*100:.2f}%")
        with col3:
            st.metric("Parametric VaR 95%", f"{latest['parametric_var']*100:.2f}%")
        with col4:
            st.metric("Historical VaR 95%", f"{latest['historical_var']*100:.2f}%")

        col5, col6 = st.columns(2)
        with col5:
            st.metric("Expected Shortfall 95%", f"{latest['expected_shortfall']*100:.2f}%")
        with col6:
            es_exceed = latest['expected_shortfall'] - latest['historical_var']
            st.metric("ES - VaR Spread", f"{es_exceed*100:.2f}%", delta="Tail risk" if es_exceed < 0 else "")

        # ── AI Analysis ──
        st.divider()
        st.subheader("✨ Trợ lý AI Phân tích VaR-CVaR VNINDEX")

        from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
        from openai import OpenAI

        today_str = date.today().strftime('%d%m%y')
        ai_cache_file = DATA_LAKE / "daily_cache" / f"var_cvar_vnindex_{ai_provider}_{today_str}.txt"

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
                                client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])

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
            _all_caches = sorted(
                list(DATA_LAKE.glob(f"daily_cache/var_cvar_vnindex_*.txt")),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            _all_caches = _all_caches[:10]
            if not _all_caches:
                st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
            else:
                _options = {}
                for _fp in _all_caches:
                    _fname = _fp.name
                    _parts = _fname.replace(".txt", "").split("_")
                    if len(_parts) >= 3:
                        _date_str = _parts[-1]
                        _provider_parts = _parts[1:-1]
                        if "var_cvar_vnindex".count("_") > 0:
                            prefix_parts_count = len("var_cvar_vnindex".split("_"))
                            _provider_parts = _parts[prefix_parts_count:-1]
                        _provider = "_".join(_provider_parts)
                        if len(_date_str) == 6 and _date_str.isdigit():
                            _date_display = f"{_date_str[:2]}/{_date_str[2:4]}/{_date_str[4:]}"
                            _provider_display = AI_PROVIDER_MAP.get(_provider, {}).get("display", _provider)
                            _label = f"{_date_display} — {_provider_display}"
                            _options[_label] = _fp
                
                if _options:
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
                else:
                    st.info("ℹ️ Không thể đọc được danh sách lịch sử.")

