"""
tools/global_financial_conditions/page.py
UI bridge cho Global Financial Conditions Monitor (GFCM).

2 tabs:
  Tab 1 — 📊 Level (raw indicators)
  Tab 2 — 🧠 Analytics (PR + PCA + AI Analysis)
"""
import os
from datetime import date

import pandas as pd
import streamlit as st

from config import DATA_LAKE, ROOT_DIR, AI_TEMPERATURE
from tools.global_financial_conditions.quant.metrics import (
    OUTPUT_COLUMNS,
    summarize_latest,
)
from tools.global_financial_conditions.ui.sidebar import render_sidebar
from tools.global_financial_conditions.ui.charts import (
    plot_level_grid,
    plot_pc1_with_regime,
    plot_percentile_grid,
    plot_pc_scatter,
    plot_credit_quality_spread,
)

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6",
                     "base_url": "https://api.moonshot.ai/v1"},
        "deepseek-v4-pro": {"display": "DeepSeek V4 Pro", "api_model": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"},
    }

GFCM_FILE = "global_financial_conditions_cache.csv"

REGIME_ICON = {"STRESS": "🔴", "ELEVATED": "🟠", "CALM": "🟢", "N/A": "⚪"}


def _load_gfcm() -> pd.DataFrame:
    """Đọc global_financial_conditions_cache.csv từ data_lake."""
    path = DATA_LAKE / GFCM_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {path}.\n"
            "Vui lòng chạy: python command/update_global_financial_conditions.py"
        )
    df = pd.read_csv(path, parse_dates=["DATE"]).set_index("DATE").sort_index()
    numeric_cols = [c for c in OUTPUT_COLUMNS if c not in ("Regime", "Driver")]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def render():
    st.title("🌐 Global Financial Conditions Monitor")
    st.caption(
        "Equity vol (VIX) + Rates vol (MOVE) + Credit (HY OAS, CCC OAS) · "
        "Static PCA composite · Regime via PC1 percentile rank 3Y"
    )

    plot_start_date = render_sidebar()

    # ── AI provider ──
    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="gfcm_ai_provider",
    )
    api_key_raw = st.sidebar.text_input(
        "API Key (hoặc shortcut 4 số):",
        type="password",
        key="gfcm_api_key",
        placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets.",
    )
    from shared.api_key_helper import resolve_api_key
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

    # ── Load data ──
    try:
        df_all = _load_gfcm()
    except FileNotFoundError as e:
        st.error(str(e))
        st.info(
            "💡 **Cách cập nhật:**\n"
            "```bash\n"
            "python command/update_global_financial_conditions.py\n"
            "```\n"
            "Trước khi chạy, đảm bảo `FRED_API_KEY` đã được set và `yfinance` đã cài."
        )
        st.stop()
        return

    if df_all.empty:
        st.warning("Cache GFCM rỗng. Vui lòng chạy updater.")
        st.stop()
        return

    summary = summarize_latest(df_all)
    rg = summary["regime"]
    rg_icon = REGIME_ICON.get(rg, "⚪")

    # ── Header metrics (chung cho cả 2 tab) ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Cập nhật gần nhất", summary["date"])
    with col2:
        st.metric(f"Regime {rg_icon}", rg)
    with col3:
        st.metric("Driver", summary["driver"])
    with col4:
        st.metric("PC1 (σ)", f"{summary['pc1']:+.2f}",
                  delta=f"5d: {summary['pc1_5d_change']:+.2f}")

    st.divider()

    # ── Filter theo plot_start_date ──
    df_plot = df_all[df_all.index >= pd.to_datetime(plot_start_date)].copy()
    if df_plot.empty:
        st.warning("Không có dữ liệu trong khoảng thời gian đã chọn.")
        st.stop()
        return

    tab_level, tab_analytics = st.tabs(["📊 Level", "🧠 Analytics (PR + PCA + AI)"])

    # ────────────────────────────────────────────────────────────────────
    # Tab 1 — Level
    # ────────────────────────────────────────────────────────────────────
    with tab_level:
        st.subheader("Giá trị tuyệt đối 4 chỉ số")
        st.caption(
            "Mức raw level — quan sát so với đường trung bình lịch sử (dotted line). "
            "Để xem xếp hạng theo phân phối lịch sử, chuyển sang tab Analytics."
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("VIX", f"{summary['vix']:.2f}")
        with col2:
            st.metric("MOVE", f"{summary['move']:.1f}")
        with col3:
            st.metric("HY OAS", f"{summary['hy_oas']:.2f}%")
        with col4:
            st.metric("CCC OAS", f"{summary['ccc_oas']:.2f}%")

        st.plotly_chart(plot_level_grid(df_plot), use_container_width=True)

        with st.expander("📋 Bảng giá trị (50 dòng gần nhất)"):
            cols_raw = ["VIX", "MOVE", "HY_OAS", "CCC_OAS", "Credit_Quality_Spread"]
            st.dataframe(
                df_all[cols_raw].tail(50).style.format({
                    "VIX": "{:.2f}", "MOVE": "{:.1f}",
                    "HY_OAS": "{:.2f}%", "CCC_OAS": "{:.2f}%",
                    "Credit_Quality_Spread": "{:.2f}%",
                }),
                use_container_width=True,
            )

    # ────────────────────────────────────────────────────────────────────
    # Tab 2 — Analytics
    # ────────────────────────────────────────────────────────────────────
    with tab_analytics:
        st.subheader("Percentile Rank · PCA · Regime")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("PC1 percentile", f"{summary['pc1_pct']*100:.0f}%")
        with col2:
            st.metric("VIX pct (3Y)", f"{summary['vix_pct']*100:.0f}%")
        with col3:
            st.metric("MOVE pct (3Y)", f"{summary['move_pct']*100:.0f}%")
        with col4:
            st.metric("HY pct (3Y)", f"{summary['hy_pct']*100:.0f}%")
        with col5:
            st.metric("CCC pct (3Y)", f"{summary['ccc_pct']*100:.0f}%")

        st.plotly_chart(plot_pc1_with_regime(df_plot), use_container_width=True)
        st.plotly_chart(plot_percentile_grid(df_plot), use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(plot_pc_scatter(df_plot, n_recent=252), use_container_width=True)
        with col_b:
            st.plotly_chart(plot_credit_quality_spread(df_plot), use_container_width=True)

        with st.expander("📋 Bảng Analytics (50 dòng gần nhất)"):
            cols_ana = ["PC1", "PC2", "PC1_pct",
                        "VIX_pct", "MOVE_pct", "HY_pct", "CCC_pct", "CQS_pct",
                        "Regime", "Driver"]
            st.dataframe(
                df_all[cols_ana].tail(50).style.format({
                    "PC1": "{:+.2f}", "PC2": "{:+.2f}",
                    "PC1_pct": "{:.2%}", "VIX_pct": "{:.2%}",
                    "MOVE_pct": "{:.2%}", "HY_pct": "{:.2%}",
                    "CCC_pct": "{:.2%}", "CQS_pct": "{:.2%}",
                }, na_rep="—"),
                use_container_width=True,
            )

        # ── AI Analysis (đặt trong Tab 2) ──
        st.divider()
        st.subheader("✨ Trợ lý AI Phân tích GFCM")

        from openai import OpenAI

        today_str = date.today().strftime("%d%m%y")
        ai_cache_file = (
            DATA_LAKE / "daily_cache"
            / f"global_financial_conditions_{ai_provider}_{today_str}.txt"
        )

        tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])

        with tab_current:
            if ai_cache_file.exists():
                st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
                with open(ai_cache_file, "r", encoding="utf-8") as f:
                    cached_result = f.read()
                with st.container(border=True):
                    st.markdown(cached_result)

                from shared.github_sync import render_sync_button
                render_sync_button(ai_cache_file, key_suffix="gfcm")

                if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="gfcm_rerun_ai"):
                    os.remove(ai_cache_file)
                    st.rerun()
            else:
                btn_label = f"🐺 Phân tích GFCM ({AI_PROVIDER_MAP[ai_provider]['display']})"
                if st.button(btn_label, type="primary", use_container_width=True,
                             key="gfcm_run_ai"):
                    if not api_key:
                        st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                    else:
                        with st.spinner("AI đang phân tích Global Financial Conditions..."):
                            try:
                                cfg = AI_PROVIDER_MAP[ai_provider]
                                client = OpenAI(api_key=api_key.strip(),
                                                base_url=cfg["base_url"])

                                prompt_path = ROOT_DIR / "promt" / "global_financial_conditions_promt.md"
                                with open(prompt_path, "r", encoding="utf-8") as f:
                                    prompt_template = f.read()

                                full_prompt = (
                                    prompt_template
                                    .replace("[Nhập ngày]", summary["date"])
                                    .replace("[VIX]", f"{summary['vix']:.2f}")
                                    .replace("[MOVE]", f"{summary['move']:.1f}")
                                    .replace("[HY_OAS]", f"{summary['hy_oas']:.2f}")
                                    .replace("[CCC_OAS]", f"{summary['ccc_oas']:.2f}")
                                    .replace("[CQS]", f"{summary['credit_quality_spread']:.2f}")
                                    .replace("[VIX_pct]", f"{summary['vix_pct']*100:.0f}")
                                    .replace("[MOVE_pct]", f"{summary['move_pct']*100:.0f}")
                                    .replace("[HY_pct]", f"{summary['hy_pct']*100:.0f}")
                                    .replace("[CCC_pct]", f"{summary['ccc_pct']*100:.0f}")
                                    .replace("[CQS_pct]", f"{summary['cqs_pct']*100:.0f}")
                                    .replace("[VIX_z]", f"{summary['vix_z']:+.2f}")
                                    .replace("[MOVE_z]", f"{summary['move_z']:+.2f}")
                                    .replace("[HY_z]", f"{summary['hy_z']:+.2f}")
                                    .replace("[CCC_z]", f"{summary['ccc_z']:+.2f}")
                                    .replace("[PC1]", f"{summary['pc1']:+.2f}")
                                    .replace("[PC2]", f"{summary['pc2']:+.2f}")
                                    .replace("[PC1_pct]", f"{summary['pc1_pct']*100:.0f}")
                                    .replace("[PC1_5d]", f"{summary['pc1_5d_change']:+.2f}")
                                    .replace("[Regime]", summary["regime"])
                                    .replace("[Driver]", summary["driver"])
                                )

                                parts = full_prompt.split("# INPUT DATA")
                                system_prompt = parts[0].strip()
                                user_prompt = (
                                    "# INPUT DATA" + parts[1].strip()
                                    if len(parts) > 1 else full_prompt
                                )

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
            _all_caches = list(DATA_LAKE.glob("daily_cache/global_financial_conditions_*.txt"))
            _options = build_history_options(
                _all_caches, "global_financial_conditions", AI_PROVIDER_MAP
            )
            if not _options:
                st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
            else:
                _selected_label = st.selectbox(
                    "📅 Chọn ngày và model:",
                    options=list(_options.keys()),
                    index=0,
                    key="gfcm_history_selector",
                )
                _sel_path = _options[_selected_label]
                with st.container(border=True):
                    try:
                        with open(_sel_path, "r", encoding="utf-8") as f:
                            st.markdown(f.read())
                    except Exception as e:
                        st.error(f"Lỗi đọc file: {e}")
