"""
tools/vnibor/page.py
UI bridge for Vietnam Interbank Market Rate (VNIBOR) Monitor.
"""
import os
from datetime import date
import pandas as pd
import streamlit as st

from config import DATA_LAKE, ROOT_DIR, AI_TEMPERATURE
from shared.page_layout import render_signal_card, tone_for_signal
from tools.vnibor.quant.metrics import (
    load_vnibor_data,
    process_vnibor_logic,
    summarize_latest,
    summarize_20d_trend,
)
from tools.vnibor.ui.sidebar import render_sidebar
from tools.vnibor.ui.charts import plot_vnibor_rates, plot_vnibor_spreads, plot_vnibor_regime

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"},
        "deepseek-v4-pro": {"display": "DeepSeek V4 Pro", "api_model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1"},
    }

VNIBOR_FILE = "LaiSuatLienNganHang_Wichart.csv"
AI_CIO_CACHE_VERSION_HEADER = "ai-cio-cache-version"
VNIBOR_AI_CACHE_VERSION = "structured_20d_trend_v2"
REGIME_ICON = {"TIGHT": "🔴", "ELEVATED": "🟠", "NORMAL": "🔵", "EASY": "🟢", "N/A": "⚪"}
SIGNAL_ICON = {"STRESS": "💥", "WARNING": "⚠️", "ACCOMMODATIVE": "🟢", "NEUTRAL": "⚪"}


def _encode_vnibor_ai_cache(content: str) -> str:
    marker = f"<!-- {AI_CIO_CACHE_VERSION_HEADER}: {VNIBOR_AI_CACHE_VERSION} -->\n"
    text = str(content or "")
    if text.startswith(marker):
        return text
    return marker + text


def _is_vnibor_ai_cache_current(content: str) -> bool:
    marker = f"<!-- {AI_CIO_CACHE_VERSION_HEADER}: {VNIBOR_AI_CACHE_VERSION} -->"
    return str(content or "").lstrip().startswith(marker)


def render():
    st.title("Vietnam Interbank Market Rate (VNIBOR) Monitor")
    st.caption(
        "Theo dõi Lãi suất Qua đêm và các kỳ hạn ngắn trên Thị trường Liên ngân hàng Việt Nam. "
        "Giúp nhận diện sớm áp lực thanh khoản hệ thống và tác động lan tỏa tới thị trường chứng khoán VN-Index."
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
        key="vnibor_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key (hoặc shortcut 4 số):",
        type="password",
        key="vnibor_api_key",
        placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)",
    )
    
    from shared.api_key_helper import resolve_api_key
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw, ai_provider)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    # ── Load and Process Data ──
    try:
        df_raw = load_vnibor_data()
        df_processed = process_vnibor_logic(df_raw)
    except FileNotFoundError as e:
        st.error(str(e))
        st.info(
            "💡 **Cách cập nhật:**\n"
            "Chạy script cập nhật trong command line:\n"
            "```bash\n"
            "python -m command.update_vnibor\n"
            "```"
        )
        st.stop()
        return

    if df_processed.empty:
        st.warning("Dữ liệu VNIBOR trống. Vui lòng chạy updater.")
        st.stop()
        return

    # ── Header metrics ──
    summary = summarize_latest(df_processed)
    trend_20d = summarize_20d_trend(df_processed, lookback=20)
    
    reg_icon = REGIME_ICON.get(summary["regime"], "⚪")
    sig_icon = SIGNAL_ICON.get(summary["signal"], "⚪")

    # Row 1: Thống kê lãi suất
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Phiên dữ liệu", summary["date"])
    with col2:
        st.metric(
            "Qua đêm _ON (%)", 
            f"{summary['overnight']:.2f}%",
            delta=f"{summary['impulse']:+.2f}%" if summary['impulse'] else None
        )
    with col3:
        st.metric("Kỳ hạn 1 Tuần (%)", f"{summary['w1']:.2f}%")
    with col4:
        st.metric("Kỳ hạn 2 Tuần (%)", f"{summary['w2']:.2f}%")

    # Row 2: Phân tích định lượng & Trạng thái
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("Z-Score (252 ngày)", f"{summary['z_score']:+.2f}")
    with col6:
        st.metric("Percentile (252 ngày)", f"{summary['percentile']*100:.1f}%")
    with col7:
        render_signal_card("Trạng thái", summary["regime"], tone=tone_for_signal(summary["regime"]), icon=reg_icon)
    with col8:
        render_signal_card("Tín hiệu", summary["signal"], tone=tone_for_signal(summary["signal"]), icon=sig_icon)

    # Row 3: Spreads (chênh lệch kỳ hạn)
    st.markdown("##### 📐 Chênh lệch kỳ hạn ngắn hạn (Term Spreads)")
    col9, col10, col11 = st.columns(3)
    with col9:
        st.metric("Spread 1W - ON (%)", f"{summary['spread_1w']:+.2f}%")
    with col10:
        st.metric("Spread 2W - ON (%)", f"{summary['spread_2w']:+.2f}%")
    with col11:
        inverted_curve = "ĐẢO NGƯỢC (Rủi ro)" if summary['spread_1w'] < 0 else "Bình thường (Dốc lên)"
        render_signal_card(
            "Đường cong Lợi suất",
            inverted_curve,
            tone="danger" if summary["spread_1w"] < 0 else "positive",
            caption="Cảnh báo thanh khoản!" if summary["spread_1w"] < 0 else None,
        )

    st.divider()

    # ── Filter theo plot_start_date ──
    df_plot = df_processed[df_processed.index >= pd.to_datetime(plot_start_date)].copy()
    if df_plot.empty:
        st.warning("Không có dữ liệu trong khoảng thời gian đã chọn.")
        st.stop()
        return

    # ── Charts tabs ──
    tab_chart1, tab_chart2, tab_chart3 = st.tabs([
        "📈 Lãi suất các kỳ hạn", 
        "📐 Chênh lệch Kỳ hạn (Spreads)", 
        "🧠 Trạng thái Thanh khoản (Regime)"
    ])
    
    with tab_chart1:
        st.plotly_chart(plot_vnibor_rates(df_plot), use_container_width=True)

        # ── AI Analysis (Đặt chung cho toàn bộ tool trực tiếp dưới đồ thị ở Tab 1) ──
        st.divider()
        st.subheader("✨ Trợ lý AI Phân tích Thanh khoản VNIBOR")

        from openai import OpenAI

        today_str = date.today().strftime("%d%m%y")
        ai_cache_file = DATA_LAKE / "daily_cache" / f"vnibor_{ai_provider}_{today_str}.txt"

        tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])

        with tab_current:
            if ai_cache_file.exists():
                st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
                with open(ai_cache_file, "r", encoding="utf-8") as f:
                    cached_result = f.read()
                if not _is_vnibor_ai_cache_current(cached_result):
                    os.remove(ai_cache_file)
                    st.rerun()
                with st.container(border=True):
                    st.markdown(cached_result)

                from shared.github_sync import render_sync_button
                render_sync_button(ai_cache_file, key_suffix="vnibor")

                if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="vnibor_rerun_ai"):
                    os.remove(ai_cache_file)
                    st.rerun()
            else:
                btn_label = f"🐺 Phân tích VNIBOR & Spillover ({AI_PROVIDER_MAP[ai_provider]['display']})"
                if st.button(btn_label, type="primary", use_container_width=True, key="vnibor_run_ai"):
                    if not api_key:
                        st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                    else:
                        with st.spinner("AI đang phân tích thanh khoản liên ngân hàng Việt Nam..."):
                            try:
                                cfg = AI_PROVIDER_MAP[ai_provider]
                                client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))

                                prompt_path = ROOT_DIR / "promt" / "vnibor_promt.md"
                                if not prompt_path.exists():
                                    st.error("Không tìm thấy file prompt mẫu vnibor_promt.md")
                                    st.stop()

                                with open(prompt_path, "r", encoding="utf-8") as f:
                                    prompt_template = f.read()

                                full_prompt = prompt_template \
                                    .replace("[Nhập ngày]", summary["date"]) \
                                    .replace("[Overnight_ON]", f"{summary['overnight']:.2f}") \
                                    .replace("[1_Week]", f"{summary['w1']:.2f}") \
                                    .replace("[2_Weeks]", f"{summary['w2']:.2f}") \
                                    .replace("[ON_Impulse]", f"{summary['impulse']:+.2f}") \
                                    .replace("[ON_ZScore]", f"{summary['z_score']:+.2f}") \
                                    .replace("[ON_Percentile]", f"{summary['percentile']:.3f}") \
                                    .replace("[Spread_1W_ON]", f"{summary['spread_1w']:+.2f}") \
                                    .replace("[Spread_2W_ON]", f"{summary['spread_2w']:+.2f}") \
                                    .replace("[Regime]", summary["regime"]) \
                                    .replace("[Signal]", summary["signal"]) \
                                    .replace("[Trend_20D_Label]", trend_20d["trend_label"]) \
                                    .replace("[ON_20D_Change]", trend_20d["on_20d_change"]) \
                                    .replace("[ON_MA5_20D_Change]", trend_20d["on_ma5_20d_change"]) \
                                    .replace("[ON_MA5_20D_Slope]", trend_20d["on_ma5_slope"]) \
                                    .replace("[ON_20D_Avg]", trend_20d["on_20d_avg"]) \
                                    .replace("[ON_20D_Min]", trend_20d["on_20d_min"]) \
                                    .replace("[ON_20D_Max]", trend_20d["on_20d_max"]) \
                                    .replace("[ON_20D_Up_Days]", trend_20d["up_days"]) \
                                    .replace("[ON_20D_Down_Days]", trend_20d["down_days"]) \
                                    .replace("[Inversion_20D_Count]", trend_20d["inversion_days"]) \
                                    .replace("[Stress_Warning_20D_Count]", trend_20d["stress_warning_days"]) \
                                    .replace("[Regime_20D_Counts]", trend_20d["regime_counts"]) \
                                    .replace("[Signal_20D_Counts]", trend_20d["signal_counts"]) \
                                    .replace("[Trend_20D_Table]", trend_20d["trend_table"])

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
                                    f.write(_encode_vnibor_ai_cache(result_text))

                                st.success("Hoàn thành phân tích!")
                                with st.container(border=True):
                                    st.markdown(result_text)

                            except Exception as e:
                                st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại!")

        with tab_history:
            from shared.history_selector import build_history_options
            _all_caches = list(DATA_LAKE.glob("daily_cache/vnibor_*.txt"))
            _options = build_history_options(_all_caches, "vnibor", AI_PROVIDER_MAP)
            if not _options:
                st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
            else:
                _selected_label = st.selectbox(
                    "📅 Chọn ngày và model:",
                    options=list(_options.keys()),
                    index=0,
                    key="vnibor_history_selector",
                )
                _sel_path = _options[_selected_label]
                with st.container(border=True):
                    try:
                        with open(_sel_path, "r", encoding="utf-8") as f:
                            st.markdown(f.read())
                    except Exception as e:
                        st.error(f"Lỗi đọc file: {e}")

    with tab_chart2:
        st.plotly_chart(plot_vnibor_spreads(df_plot), use_container_width=True)
    with tab_chart3:
        st.plotly_chart(plot_vnibor_regime(df_plot), use_container_width=True)

    with st.expander("📋 Bảng dữ liệu chi tiết (50 phiên gần nhất)"):
        st.dataframe(
            df_processed.tail(50).style.format({
                "Overnight_ON": "{:.2f}%", 
                "1_Week": "{:.2f}%", 
                "2_Weeks": "{:.2f}%",
                "ON_Impulse": "{:+.2f}%", 
                "ON_ZScore": "{:+.2f}", 
                "ON_Percentile": "{:.1%}",
                "Spread_1W_ON": "{:+.2f}%", 
                "Spread_2W_ON": "{:+.2f}%"
            }),
            use_container_width=True,
        )
