"""
tools/fed_liquidity/page.py
UI bridge cho Fed Liquidity Monitor.
"""
import os
from datetime import date

import pandas as pd
import streamlit as st

from config import DATA_LAKE, ROOT_DIR, AI_TEMPERATURE
from shared.page_layout import render_signal_card, tone_for_signal
from tools.fed_liquidity.quant.metrics import OUTPUT_COLUMNS, summarize_latest
from tools.fed_liquidity.ui.sidebar import render_sidebar
from tools.fed_liquidity.ui.charts import plot_net_liquidity, plot_momentum, plot_zscore

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"},
        "deepseek-v4-pro": {"display": "DeepSeek V4 Pro", "api_model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1"},
    }

FED_LIQUIDITY_FILE = "fed_liquidity_cache.csv"


def _load_fed_liquidity() -> pd.DataFrame:
    """Đọc fed_liquidity_cache.csv từ data_lake."""
    path = DATA_LAKE / FED_LIQUIDITY_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {path}.\n"
            "Vui lòng chạy: python command/update_fed_liquidity.py"
        )
    df = pd.read_csv(path, parse_dates=["DATE"])
    df = df.set_index("DATE").sort_index()
    # Đảm bảo đúng dtype
    numeric_cols = [c for c in OUTPUT_COLUMNS if c != "Signal"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def render():
    st.title("🏦 Fed Liquidity Monitor")
    st.caption(
        "Net Liquidity = WALCL − WTREGEN − RRPONTSYD · "
        "Tín hiệu ADD/CUT/HOLD dựa trên Impulse EMA(4) + Z-Score 52 tuần."
    )

    plot_start_date = render_sidebar()

    # ── AI provider chọn từ sidebar ──
    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="fed_liq_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key (hoặc shortcut 4 số):",
        type="password",
        key="fed_liq_api_key",
        placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)",
    )
    from shared.api_key_helper import resolve_api_key
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    # ── Load data ──
    try:
        df_all = _load_fed_liquidity()
    except FileNotFoundError as e:
        st.error(str(e))
        st.info(
            "💡 **Cách cập nhật:**\n"
            "```bash\n"
            "python command/update_fed_liquidity.py\n"
            "```\n"
            "Trước khi chạy, đảm bảo biến môi trường `FRED_API_KEY` đã được set."
        )
        st.stop()
        return

    if df_all.empty:
        st.warning("Cache Fed Liquidity rỗng. Vui lòng chạy updater.")
        st.stop()
        return

    # ── Header metrics ──
    summary = summarize_latest(df_all)
    sig = summary["signal"]
    sig_color_map = {"ADD": "🟢", "CUT": "🔴", "HOLD": "🟡"}
    sig_icon = sig_color_map.get(sig, "⚪")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Cập nhật gần nhất", summary["date"])
    with col2:
        st.metric("Net Liquidity ($M)", f"{summary['net_liquidity']:,.0f}",
                  delta=f"{summary['impulse']:+,.0f}" if summary['impulse'] else None)
    with col3:
        st.metric("Z-Score (52W)", f"{summary['z_score']:+.2f}")
    with col4:
        render_signal_card("Signal", sig, tone=tone_for_signal(sig), icon=sig_icon)

    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("WALCL", f"{summary['walcl']:,.0f}")
    with col6:
        st.metric("WTREGEN (TGA)", f"{summary['wtregen']:,.0f}")
    with col7:
        st.metric("RRPONTSYD", f"{summary['rrpontsyd']:,.0f}")

    st.divider()

    # ── Filter theo plot_start_date ──
    df_plot = df_all[df_all.index >= pd.to_datetime(plot_start_date)].copy()
    if df_plot.empty:
        st.warning("Không có dữ liệu trong khoảng thời gian đã chọn.")
        st.stop()
        return

    # ── Charts ──
    st.plotly_chart(plot_net_liquidity(df_plot), use_container_width=True)
    st.plotly_chart(plot_momentum(df_plot), use_container_width=True)

    with st.expander("📊 Z-Score chi tiết"):
        st.plotly_chart(plot_zscore(df_plot.dropna(subset=["Z_Score"])), use_container_width=True)

    with st.expander("📋 Bảng dữ liệu (50 hàng gần nhất)"):
        st.dataframe(
            df_all.tail(50).style.format({
                "WALCL": "{:,.0f}", "WTREGEN": "{:,.0f}", "RRPONTSYD": "{:,.0f}",
                "Net_Liquidity": "{:,.0f}", "Impulse": "{:+,.0f}",
                "Impulse_EMA": "{:+,.0f}", "Z_Score": "{:+.2f}",
            }),
            use_container_width=True,
        )

    # ── AI Analysis ──
    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Fed Liquidity")

    from openai import OpenAI

    today_str = date.today().strftime("%d%m%y")
    ai_cache_file = DATA_LAKE / "daily_cache" / f"fed_liquidity_{ai_provider}_{today_str}.txt"

    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])

    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="fed_liq")

            if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="fed_liq_rerun_ai"):
                os.remove(ai_cache_file)
                st.rerun()
        else:
            btn_label = f"🐺 Phân tích Fed Liquidity ({AI_PROVIDER_MAP[ai_provider]['display']})"
            if st.button(btn_label, type="primary", use_container_width=True, key="fed_liq_run_ai"):
                if not api_key:
                    st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                else:
                    with st.spinner("AI đang phân tích thanh khoản Fed..."):
                        try:
                            cfg = AI_PROVIDER_MAP[ai_provider]
                            client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))

                            prompt_path = ROOT_DIR / "promt" / "fed_liquidity_promt.md"
                            with open(prompt_path, "r", encoding="utf-8") as f:
                                prompt_template = f.read()

                            full_prompt = prompt_template \
                                .replace("[Nhập ngày]", summary["date"]) \
                                .replace("[Net Liquidity]", f"{summary['net_liquidity']:,.0f}") \
                                .replace("[WALCL]", f"{summary['walcl']:,.0f}") \
                                .replace("[WTREGEN]", f"{summary['wtregen']:,.0f}") \
                                .replace("[RRPONTSYD]", f"{summary['rrpontsyd']:,.0f}") \
                                .replace("[Impulse]", f"{summary['impulse']:+,.0f}") \
                                .replace("[Impulse_EMA]", f"{summary['impulse_ema']:+,.0f}") \
                                .replace("[Z_Score]", f"{summary['z_score']:+.2f}") \
                                .replace("[Signal]", summary["signal"])

                            parts = full_prompt.split("# INPUT DATA")
                            system_prompt = parts[0].strip()
                            user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

                            response = client.chat.completions.create(
                                model=cfg["api_model"],
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt},
                                ],
                                temperature=cfg.get("temperature", AI_TEMPERATURE),
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
        _all_caches = list(DATA_LAKE.glob("daily_cache/fed_liquidity_*.txt"))
        _options = build_history_options(_all_caches, "fed_liquidity", AI_PROVIDER_MAP)
        if not _options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            _selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(_options.keys()),
                index=0,
                key="fed_liq_history_selector",
            )
            _sel_path = _options[_selected_label]
            with st.container(border=True):
                try:
                    with open(_sel_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")
