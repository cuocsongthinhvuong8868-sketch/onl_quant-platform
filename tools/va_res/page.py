import streamlit as st
import pandas as pd
import polars as pl
import numpy as np
import os
import datetime
from shared.data_loader import load_close_prices
from tools.va_res.quant.metrics import SystemicRiskEngine, RiskConfig
from tools.va_res.ui.sidebar import render_sidebar
from tools.va_res.ui.charts import plot_individual_risk, plot_systemic_risk, plot_complacency_index

try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {"display": "Kimi 2.6", "api_model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"},
        "deepseek-v4-pro": {"display": "DeepSeek V4 Pro", "api_model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    }

VN30_TICKERS = ['ACB', 'BCM', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 'MBB', 'MSN', 'MWG', 'PLX', 'POW', 'SAB', 'SHB', 'SSB', 'SSI', 'STB', 'TCB', 'TPB', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VRE']

MARKET_TICKERS = {
    'Ngân Hàng': ['VCB', 'BID', 'CTG', 'MBB', 'TCB', 'VPB', 'ACB', 'STB', 'HDB', 'VIB', 'SHB', 'TPB', 'SSB', 'LPB', 'MSB', 'OCB', 'EIB'],
    'Bất Động Sản': ['VIC', 'VHM', 'VRE', 'NVL', 'DIG', 'DXG', 'KDH', 'NLG', 'PDR', 'SCR', 'HDG', 'CRE', 'IJC', 'HQC', 'CEO'],
    'Chứng Khoán': ['SSI', 'VND', 'VCI', 'HCM', 'FTS', 'BSI', 'VIX', 'CTS', 'ORS', 'AGR', 'VDS'], 
    'Thép / Vật Liệu': ['HPG', 'HSG', 'NKG', 'HT1', 'BCC', 'SMC', 'TLH', 'BMP', 'KSB'],
    'Xây Dựng / Đầu Tư Công': ['VCG', 'CTD', 'CII', 'HHV', 'LCG', 'FCN', 'PC1'],
    'Hóa Chất / Phân Bón': ['DGC', 'DPM', 'DCM', 'CSV', 'LAS'],
    'Dầu Khí': ['GAS', 'PLX', 'PVD', 'PVT', 'PVS', 'BSR', 'CNG', 'VIP', 'VTO'], 
    'Bán Lẻ': ['MWG', 'PNJ', 'FRT', 'DGW', 'PET', 'HAX'],
    'Khu Công Nghiệp': ['BCM', 'KBC', 'SZC', 'VGC', 'PHR', 'ITA', 'D2D', 'IDC'],
    'Công Nghệ': ['FPT', 'CMG', 'ELC', 'SAM', 'VGI'],
    'Cảng Biển / Logistics': ['GMD', 'HAH', 'VSC', 'TCL', 'VOS'],
    'Nông Nghiệp / Thủy Sản': ['VHC', 'ANV', 'DBC', 'HAG', 'HNG', 'FMC', 'IDI', 'PAN', 'BAF'],
    'Tiện Ích': ['POW', 'REE', 'NT2', 'GEG', 'VSH', 'BWE']
}
ALL_MARKET_TICKERS = [ticker for sublist in MARKET_TICKERS.values() for ticker in sublist]

STRESS_THRESHOLD_VN30 = 0.40
COMPLACENCY_THRESHOLD_MKT = 0.80

def show():
    st.title("Hệ Thống Phân Tích Hệ Số Tự Mãn  & Định Giá Sai (VaR-ES)")
    st.caption("Công cụ giám sát Value at Risk & Expected Shortfall (Polars/Numba backend).")

    menu, plot_start_date = render_sidebar()
    
    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="va_res_ai_provider",
    )
    api_key = st.sidebar.text_input("API Key", type="password", key="va_res_api_key")

    try:
        df_price_pandas = load_close_prices()
        # Reset index to make Date a column for Polars
        df_price_pandas = df_price_pandas.reset_index()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    engine = SystemicRiskEngine()

    if menu == "A. Phân tích Cổ phiếu Riêng lẻ":
        st.subheader("Phân Tích Rủi Ro Cổ Phiếu Riêng Lẻ")
        ticker = st.text_input("Nhập mã cổ phiếu (VD: STB, HPG):", "STB").upper()
        if st.button("Chạy Phân Tích"):
            if ticker not in df_price_pandas.columns:
                st.error(f"Không tìm thấy dữ liệu cho mã {ticker}.")
            else:
                date_col = df_price_pandas.columns[0]
                df_ticker_pandas = df_price_pandas[[date_col, ticker]].dropna()
                df_ticker_pl = pl.from_pandas(df_ticker_pandas)
                
                with st.spinner(f"Đang xử lý dữ liệu cho {ticker}..."):
                    df_metrics = engine.calculate_risk_metrics(df_ticker_pl, method='cornish_fisher')
                    
                    # Convert to pandas for plotting
                    df_plot = df_metrics.to_pandas().set_index(date_col)
                    df_plot = df_plot[df_plot.index >= pd.to_datetime(plot_start_date)]
                    
                    p_ret = df_plot['return']
                    p_std20 = p_ret.rolling(window=20, min_periods=1).std() * -1
                    p_var = df_plot['VaR']
                    p_es = df_plot['ES']
                    
                    fig_ply = plot_individual_risk(p_std20, p_var, p_es, ticker)
                    st.plotly_chart(fig_ply, use_container_width=True)

    elif menu == "B. Cảnh báo Sập gãy (Rổ VN30)":
        st.subheader("Cảnh báo Sập gãy - Lây lan Khủng hoảng (VN30)")
        if st.button("Quét Rủi Ro Hệ Thống"):
            available_vn30 = [t for t in VN30_TICKERS if t in df_price_pandas.columns]
            date_col = df_price_pandas.columns[0]
            df_vn30_pandas = df_price_pandas[[date_col] + available_vn30]
            df_vn30_pl = pl.from_pandas(df_vn30_pandas)
            
            with st.spinner("Đang phân tích rổ VN30..."):
                df_metrics = engine.calculate_risk_metrics(df_vn30_pl, method='cornish_fisher')
                df_contagion = engine.calculate_contagion_index(df_metrics)
                
                df_plot = df_contagion.to_pandas().set_index(date_col)
                df_plot = df_plot[df_plot.index >= pd.to_datetime(plot_start_date)]
                stress_index = df_plot['Contagion_Index']
                
                fig_ply = plot_systemic_risk(stress_index, STRESS_THRESHOLD_VN30)
                st.plotly_chart(fig_ply, use_container_width=True)
                
                # ── Chi tiết kết quả tính toán VN30 ──
                latest_date = df_metrics[date_col].max()
                df_latest = df_metrics.filter(pl.col(date_col) == latest_date).to_pandas()
                df_latest['breach_margin'] = df_latest['VaR'] - df_latest['return']
                breached = df_latest[df_latest['return'] < df_latest['VaR']]
                total_vn30 = len(available_vn30)
                breached_count = len(breached)
                breach_pct = (breached_count / total_vn30 * 100.0) if total_vn30 > 0 else 0.0
                
                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.metric("Tổng số mã VN30", total_vn30)
                with col_m2:
                    st.metric("Số mã thủng VaR", breached_count, delta=f"{breach_pct:.1f}%")
                with col_m3:
                    latest_stress = stress_index.iloc[-1] if not stress_index.empty else 0.0
                    st.metric("Stress Index", f"{latest_stress:.2f}%", delta="🔴 Vượt ngưỡng" if latest_stress > STRESS_THRESHOLD_VN30 * 100 else "🟢 An toàn")
                
                if not breached.empty:
                    top3_breach = breached.sort_values(by='breach_margin', ascending=False).head(3)
                    st.markdown("**🔥 Top 3 mã thủng VaR sâu nhất (theo breach margin):**")
                    for idx, row in top3_breach.iterrows():
                        st.markdown(f"- **{row['ticker']}**: breach margin = `{row['breach_margin']*100:.2f}%`, Return = `{row['return']*100:.2f}%`, VaR = `{row['VaR']*100:.2f}%`")
                else:
                    st.success("✅ Không có mã nào trong rổ VN30 thủng VaR hôm nay.")
                
                # Bảng trạng thái T0 đầy đủ
                risk_table = pd.DataFrame({
                    'Return (%)': df_latest['return'] * 100, 
                    'CF VaR 95% (%)': df_latest['VaR'] * 100, 
                    'ES (%)': df_latest['ES'] * 100,
                    'Breach Margin (%)': df_latest['breach_margin'] * 100,
                    'Tình trạng': np.where(df_latest['return'] < df_latest['VaR'], 'Cảnh báo Lây lan', 'Bình thường')
                }, index=df_latest['ticker']).round(2).dropna().sort_values(by=['Tình trạng', 'Breach Margin (%)'], ascending=[True, False])
                
                def highlight_crash(row):
                    if row['Tình trạng'] == 'Cảnh báo Lây lan': return ['font-weight: bold; color: red'] * len(row)
                    return [''] * len(row)
                st.dataframe(risk_table.style.apply(highlight_crash, axis=1), use_container_width=True)

    elif menu == "C. Cảnh báo Định giá sai Rủi ro (Toàn thị trường)":
        st.subheader("Cảnh báo Định giá sai Rủi ro & Bất cân xứng Mức Bù Rủi Ro")
        if st.button("Quét Định Giá Rủi Ro"):
            available_tickers = [t for t in ALL_MARKET_TICKERS if t in df_price_pandas.columns]
            date_col = df_price_pandas.columns[0]
            
            cols_to_select = [date_col] + available_tickers
            if 'VNINDEX' in df_price_pandas.columns:
                cols_to_select.append('VNINDEX')
            
            df_mkt_pandas = df_price_pandas[cols_to_select]
            
            if 'VNINDEX' not in df_mkt_pandas.columns:
                try:
                    from shared.data_loader import load_custom
                    vnindex_df = load_custom("vnindex_cache.csv").reset_index()
                    idx_col = "VNINDEX" if "VNINDEX" in vnindex_df.columns else vnindex_df.columns[1]
                    vni_date_col = vnindex_df.columns[0]
                    df_mkt_pandas = df_mkt_pandas.merge(
                        vnindex_df[[vni_date_col, idx_col]].rename(columns={idx_col: 'VNINDEX', vni_date_col: date_col}),
                        on=date_col, how='left'
                    )
                    if df_mkt_pandas['VNINDEX'].isna().all():
                        st.warning("VNINDEX cache không khớp timeline, dùng Synthetic Index.")
                        df_mkt_pandas['VNINDEX'] = df_mkt_pandas[available_tickers].mean(axis=1)
                except FileNotFoundError:
                    st.warning("Không có dữ liệu VNINDEX, dùng Synthetic Index.")
                    df_mkt_pandas['VNINDEX'] = df_mkt_pandas[available_tickers].mean(axis=1)
                
            df_mkt_pl = pl.from_pandas(df_mkt_pandas)
            
            with st.spinner("Đang tính toán hệ số trượt động & rủi ro nền (Polars)..."):
                df_metrics = engine.calculate_risk_metrics(df_mkt_pl, method='cornish_fisher')
                df_complacency = engine.calculate_complacency_index(df_metrics)
                
                # Plot Complacency Index
                df_comp_agg = df_complacency.group_by(date_col).agg(
                    (pl.col("is_mispriced").sum() / len(available_tickers) * 100).alias("Complacency_Index")
                ).sort(date_col)
                
                df_plot = df_comp_agg.to_pandas().set_index(date_col)
                df_plot = df_plot[df_plot.index >= pd.to_datetime(plot_start_date)]
                
                fig_ply = plot_complacency_index(df_plot['Complacency_Index'], COMPLACENCY_THRESHOLD_MKT)
                st.plotly_chart(fig_ply, use_container_width=True)

                # Status Table
                df_status = engine.get_latest_risk_status(df_complacency)
                
                # Add Sector info
                df_status_pd = df_status.to_pandas()
                sectors = []
                for t in df_status_pd['ticker']:
                    sector = next((s for s, t_list in MARKET_TICKERS.items() if t in t_list), "Khác")
                    sectors.append(sector)
                df_status_pd['Ngành'] = sectors
                
                # Format table
                df_status_pd['Spread (%)'] = (df_status_pd['Spread'] * 100).round(2)
                df_status_pd['Ngưỡng động (%)'] = (df_status_pd['dynamic_threshold'] * 100).round(2)
                df_display = df_status_pd[['ticker', 'Ngành', 'Spread (%)', 'Ngưỡng động (%)', 'Status']].set_index('ticker')
                df_display.rename(columns={'Status': 'Tình trạng'}, inplace=True)
                
                def highlight_mispriced(row):
                    if row['Tình trạng'] == 'Risk Mispriced': return ['font-weight: bold; color: darkorange'] * len(row)
                    return [''] * len(row)
                st.dataframe(df_display.style.apply(highlight_mispriced, axis=1), use_container_width=True)

                # Lưu vào session_state để AI block sử dụng
                st.session_state.vares_c_complacency = float(df_comp_agg.to_pandas().iloc[-1]['Complacency_Index'])
                st.session_state.vares_c_status_pd = df_status_pd
                st.session_state.vares_c_datecol = date_col

        # ── AI Analysis: chỉ ở Module C, kèm dữ liệu Module B (VN30 Stress) ──
        from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
        from datetime import date
        from openai import OpenAI
        
        today_str = date.today().strftime('%d%m%y')
        ai_cache_file = DATA_LAKE / "daily_cache" / f"va_res_{ai_provider}_{today_str}.txt"
        
        has_c_data = "vares_c_complacency" in st.session_state
        
        if ai_cache_file.exists() or has_c_data:
            st.divider()
            st.subheader("✨ Trợ lý AI Phân tích VaRES Tổng hợp (VN30 Stress + Thị trường Complacency)")
            
            if ai_cache_file.exists():
                st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
                with open(ai_cache_file, "r", encoding="utf-8") as f:
                    cached_result = f.read()
                with st.container(border=True):
                    st.markdown(cached_result)

                if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="va_res_rerun_ai"):
                    os.remove(ai_cache_file)
                    st.rerun()
            elif has_c_data:
                btn_label = f"🐺 Phân tích VaRES Tổng hợp ({AI_PROVIDER_MAP[ai_provider]['display']})"
                if st.button(btn_label, type="primary", use_container_width=True, key="va_res_run_ai"):
                    if not api_key:
                        st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                    else:
                        with st.spinner("AI đang phân tích rủi ro hệ thống VaRES..."):
                            try:
                                date_col = st.session_state.vares_c_datecol
                                df_status_pd = st.session_state.vares_c_status_pd
                                
                                # ── Tính Module B (VN30 Stress) inline ──
                                available_vn30 = [t for t in VN30_TICKERS if t in df_price_pandas.columns]
                                df_vn30_pandas = df_price_pandas[[date_col] + available_vn30]
                                df_vn30_pl = pl.from_pandas(df_vn30_pandas)
                                df_metrics30 = engine.calculate_risk_metrics(df_vn30_pl, method='cornish_fisher')
                                df_contagion = engine.calculate_contagion_index(df_metrics30)
                                
                                latest_date_b = df_metrics30[date_col].max()
                                df_latest_30 = df_metrics30.filter(pl.col(date_col) == latest_date_b).to_pandas()
                                df_latest_30['breach_margin'] = df_latest_30['VaR'] - df_latest_30['return']
                                breached_30 = df_latest_30[df_latest_30['return'] < df_latest_30['VaR']]
                                stress_index = df_contagion.to_pandas().iloc[-1]['Contagion_Index']
                                
                                if not breached_30.empty:
                                    top_3_crash = breached_30.sort_values(by='breach_margin', ascending=False).head(3)
                                    top_3_crash_str = ", ".join([f"{row['ticker']} (margin {row['breach_margin']*100:.2f}%)" for _, row in top_3_crash.iterrows()])
                                    breached_count = len(breached_30)
                                else:
                                    top_3_crash_str = "Không có"
                                    breached_count = 0
                                
                                # ── Module C data từ session_state ──
                                latest_complacency = st.session_state.vares_c_complacency
                                mispriced_df = df_status_pd[df_status_pd['Status'] == 'Risk Mispriced']
                                if not mispriced_df.empty:
                                    top_3_mis = mispriced_df.sort_values(by='Spread (%)', ascending=True).head(3)
                                    top_3_mis_str = ", ".join([f"{row['ticker']} (Spread {row['Spread (%)']:.2f}%)" for _, row in top_3_mis.iterrows()])
                                    mispriced_count = len(mispriced_df)
                                else:
                                    top_3_mis_str = "Không có"
                                    mispriced_count = 0
                                
                                # ── Gọi AI ──
                                cfg = AI_PROVIDER_MAP[ai_provider]
                                client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])

                                with open(str(ROOT_DIR / "promt" / "va_res_promt.md"), "r", encoding="utf-8") as f:
                                    prompt_template = f.read()

                                date_str = latest_date_b.strftime('%d/%m/%Y') if hasattr(latest_date_b, 'strftime') else str(latest_date_b)
                                full_prompt = prompt_template
                                full_prompt = full_prompt.replace("[Nhập ngày]", date_str)
                                full_prompt = full_prompt.replace("[Stress Index %]", f"{stress_index:.2f}%")
                                full_prompt = full_prompt.replace("[Breached Count]", str(breached_count))
                                full_prompt = full_prompt.replace("[Top 3 Crash]", top_3_crash_str)
                                full_prompt = full_prompt.replace("[Complacency Index %]", f"{latest_complacency:.2f}%")
                                full_prompt = full_prompt.replace("[Mispriced Count]", str(mispriced_count))
                                full_prompt = full_prompt.replace("[Top 3 Mispriced]", top_3_mis_str)

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
                                st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại!")
