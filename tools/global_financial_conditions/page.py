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
    plot_level_volatility,
    plot_level_credit,
    plot_level_macro,
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
    col_title, col_handbook = st.columns([5, 1])
    with col_title:
        st.title("🌐 Global Financial Conditions Monitor")
        st.caption(
            "11 indicators · Vol (VIX/MOVE/SKEW/OVX/VVIX) + Credit (HY/CCC/IG/EM OAS) + Macro (2s10s/DXY) · "
            "Static PCA 6-core composite · Regime via PC1 percentile rank 1Y"
        )
    with col_handbook:
        st.write("")  # spacer để align với title
        handbook_path = ROOT_DIR / "docs" / "GFCM-handbook.md"
        if handbook_path.exists():
            with open(handbook_path, "r", encoding="utf-8") as _f:
                _handbook_content = _f.read()
            st.download_button(
                label="📖 Tải Handbook",
                data=_handbook_content,
                file_name="GFCM-handbook.md",
                mime="text/markdown",
                use_container_width=True,
                help="Tải handbook giải thích chi tiết tool GFCM (mục tiêu, 11 indicators, PCA, regime logic, cách đọc dashboard).",
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
        st.metric("PC1 EMA(5) (σ)", f"{summary['pc1_smooth']:+.2f}",
                  delta=f"5d raw: {summary['pc1_5d_change']:+.2f}",
                  help=f"PC1 raw hôm nay: {summary['pc1']:+.2f}σ — đã smooth bằng EMA(5)")

    st.divider()

    # ── Filter theo plot_start_date ──
    df_plot = df_all[df_all.index >= pd.to_datetime(plot_start_date)].copy()
    if df_plot.empty:
        st.warning("Không có dữ liệu trong khoảng thời gian đã chọn.")
        st.stop()
        return

    tab_level, tab_analytics = st.tabs(["📊 Level", "🧠 Analytics (PR + PCA + AI)"])

    # ────────────────────────────────────────────────────────────────────
    # Tab 1 — Level (3 sub-grids: Vol / Credit / Macro)
    # ────────────────────────────────────────────────────────────────────
    with tab_level:
        st.subheader("Giá trị tuyệt đối — 11 indicators")
        st.caption(
            "Raw level so với mean lịch sử (dotted line). "
            "Để xem xếp hạng theo phân phối, chuyển sang tab Analytics."
        )

        # Volatility metrics + chart
        st.markdown("##### ⚡ Volatility (5)")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: st.metric("VIX", f"{summary['vix']:.2f}")
        with c2: st.metric("MOVE", f"{summary['move']:.1f}")
        with c3: st.metric("SKEW", f"{summary['skew']:.1f}")
        with c4: st.metric("OVX", f"{summary['ovx']:.2f}")
        with c5: st.metric("VVIX", f"{summary['vvix']:.1f}")
        st.plotly_chart(plot_level_volatility(df_plot), use_container_width=True)

        st.divider()

        # Credit metrics + chart
        st.markdown("##### 💳 Credit Spreads (4)")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("HY OAS", f"{summary['hy_oas']:.2f}%")
        with c2: st.metric("CCC OAS", f"{summary['ccc_oas']:.2f}%")
        with c3: st.metric("IG OAS", f"{summary['ig_oas']:.2f}%")
        with c4: st.metric("EM OAS", f"{summary['em_oas']:.2f}%")
        st.plotly_chart(plot_level_credit(df_plot), use_container_width=True)

        st.divider()

        # Macro metrics + chart
        st.markdown("##### 🌍 Macro Overlay (2)")
        c1, c2 = st.columns(2)
        with c1: st.metric("2s10s (%)", f"{summary['t10y2y']:+.2f}")
        with c2: st.metric("DXY", f"{summary['dxy']:.2f}")
        st.plotly_chart(plot_level_macro(df_plot), use_container_width=True)

        with st.expander("📋 Bảng giá trị (50 dòng gần nhất)"):
            cols_raw = [
                "VIX", "MOVE", "SKEW", "OVX", "VVIX",
                "HY_OAS", "CCC_OAS", "IG_OAS", "EM_OAS",
                "T10Y2Y", "DXY",
                "Credit_Quality_Spread",
            ]
            cols_available = [c for c in cols_raw if c in df_all.columns]
            st.dataframe(
                df_all[cols_available].tail(50).style.format({
                    "VIX": "{:.2f}", "MOVE": "{:.1f}", "SKEW": "{:.1f}",
                    "OVX": "{:.2f}", "VVIX": "{:.1f}",
                    "HY_OAS": "{:.2f}%", "CCC_OAS": "{:.2f}%",
                    "IG_OAS": "{:.2f}%", "EM_OAS": "{:.2f}%",
                    "T10Y2Y": "{:+.2f}", "DXY": "{:.2f}",
                    "Credit_Quality_Spread": "{:.2f}%",
                }),
                use_container_width=True,
            )

    # ────────────────────────────────────────────────────────────────────
    # Tab 2 — Analytics
    # ────────────────────────────────────────────────────────────────────
    with tab_analytics:
        st.subheader("Percentile Rank · PCA · Regime")

        # Row 1: PC1 + 6 PCA-core percentiles
        st.markdown("**PCA core (6 series)**")
        col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
        with col1: st.metric("PC1 pct", f"{summary['pc1_pct']*100:.0f}%")
        with col2: st.metric("VIX pct", f"{summary['vix_pct']*100:.0f}%")
        with col3: st.metric("MOVE pct", f"{summary['move_pct']*100:.0f}%")
        with col4: st.metric("SKEW pct", f"{summary['skew_pct']*100:.0f}%")
        with col5: st.metric("HY pct", f"{summary['hy_pct']*100:.0f}%")
        with col6: st.metric("CCC pct", f"{summary['ccc_pct']*100:.0f}%")
        with col7: st.metric("IG pct", f"{summary['ig_pct']*100:.0f}%")

        # Row 2: 5 auxiliary
        st.markdown("**Auxiliary (5 series — không vào PCA)**")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: st.metric("OVX pct", f"{summary['ovx_pct']*100:.0f}%")
        with c2: st.metric("VVIX pct", f"{summary['vvix_pct']*100:.0f}%")
        with c3: st.metric("EM pct", f"{summary['em_pct']*100:.0f}%")
        with c4: st.metric("2s10s pct", f"{summary['t10y2y_pct']*100:.0f}%")
        with c5: st.metric("DXY pct", f"{summary['dxy_pct']*100:.0f}%")

        st.plotly_chart(plot_pc1_with_regime(df_plot), use_container_width=True)
        st.plotly_chart(plot_percentile_grid(df_plot), use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(plot_pc_scatter(df_plot, n_recent=252), use_container_width=True)
        with col_b:
            st.plotly_chart(plot_credit_quality_spread(df_plot), use_container_width=True)

        with st.expander("📋 Bảng Analytics (50 dòng gần nhất)"):
            cols_ana = ["PC1", "PC1_smooth", "PC2", "PC1_pct",
                        "VIX_pct", "MOVE_pct", "SKEW_pct",
                        "HY_pct", "CCC_pct", "IG_pct",
                        "OVX_pct", "VVIX_pct", "EM_pct",
                        "T10Y2Y_pct", "DXY_pct", "CQS_pct",
                        "Regime", "Driver"]
            cols_avail = [c for c in cols_ana if c in df_all.columns]
            pct_fmt = {c: "{:.2%}" for c in cols_avail if c.endswith("_pct")}
            pct_fmt.update({"PC1": "{:+.2f}", "PC1_smooth": "{:+.2f}", "PC2": "{:+.2f}"})
            st.dataframe(
                df_all[cols_avail].tail(50).style.format(pct_fmt, na_rep="—"),
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
                                    # Volatility group
                                    .replace("[VIX]", f"{summary['vix']:.2f}")
                                    .replace("[MOVE]", f"{summary['move']:.1f}")
                                    .replace("[SKEW]", f"{summary['skew']:.1f}")
                                    .replace("[OVX]", f"{summary['ovx']:.2f}")
                                    .replace("[VVIX]", f"{summary['vvix']:.1f}")
                                    # Credit group
                                    .replace("[HY_OAS]", f"{summary['hy_oas']:.2f}")
                                    .replace("[CCC_OAS]", f"{summary['ccc_oas']:.2f}")
                                    .replace("[IG_OAS]", f"{summary['ig_oas']:.2f}")
                                    .replace("[EM_OAS]", f"{summary['em_oas']:.2f}")
                                    .replace("[CQS]", f"{summary['credit_quality_spread']:.2f}")
                                    # Macro group
                                    .replace("[T10Y2Y]", f"{summary['t10y2y']:+.2f}")
                                    .replace("[DXY]", f"{summary['dxy']:.2f}")
                                    # Percentile ranks 1Y (11 indicators)
                                    .replace("[VIX_pct]", f"{summary['vix_pct']*100:.0f}")
                                    .replace("[MOVE_pct]", f"{summary['move_pct']*100:.0f}")
                                    .replace("[SKEW_pct]", f"{summary['skew_pct']*100:.0f}")
                                    .replace("[OVX_pct]", f"{summary['ovx_pct']*100:.0f}")
                                    .replace("[VVIX_pct]", f"{summary['vvix_pct']*100:.0f}")
                                    .replace("[HY_pct]", f"{summary['hy_pct']*100:.0f}")
                                    .replace("[CCC_pct]", f"{summary['ccc_pct']*100:.0f}")
                                    .replace("[IG_pct]", f"{summary['ig_pct']*100:.0f}")
                                    .replace("[EM_pct]", f"{summary['em_pct']*100:.0f}")
                                    .replace("[T10Y2Y_pct]", f"{summary['t10y2y_pct']*100:.0f}")
                                    .replace("[DXY_pct]", f"{summary['dxy_pct']*100:.0f}")
                                    .replace("[CQS_pct]", f"{summary['cqs_pct']*100:.0f}")
                                    # Z-scores 1Y (chỉ inject 6 PCA cores cho prompt gọn)
                                    .replace("[VIX_z]", f"{summary['vix_z']:+.2f}")
                                    .replace("[MOVE_z]", f"{summary['move_z']:+.2f}")
                                    .replace("[SKEW_z]", f"{summary['skew_z']:+.2f}")
                                    .replace("[HY_z]", f"{summary['hy_z']:+.2f}")
                                    .replace("[CCC_z]", f"{summary['ccc_z']:+.2f}")
                                    .replace("[IG_z]", f"{summary['ig_z']:+.2f}")
                                    # PCA + classification — PC1 đã smooth EMA(5), PC1_raw để
                                    # AI thấy noise gốc nếu cần so sánh
                                    .replace("[PC1]", f"{summary['pc1_smooth']:+.2f}")
                                    .replace("[PC1_raw]", f"{summary['pc1']:+.2f}")
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
