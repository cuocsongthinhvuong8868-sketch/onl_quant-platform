import os
from datetime import date
import pandas as pd
import streamlit as st
from openai import OpenAI
from config import DATA_LAKE, ROOT_DIR, AI_MODEL, AI_TEMPERATURE
from shared.data_loader import load_close_prices, load_custom

# Import logic Fear Greed
from tools.fear_greed.quant.metrics import calculate_quant_metrics
from tools.fear_greed.quant.scoring import calculate_risk_score
from tools.upside_ratio.quant.metrics import build_breadth_series
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc
# Import logic Manipulation
from tools.manipulation.quant.engine import prepare_data as prep_mani, compute_metrics as comp_mani, classify_regime
# Import logic Dispersion
from tools.dispersion.quant.metrics import calculate_dispersion_metrics, fit_rolling_correlation
# Import logic Upside Ratio

# Import logic Risk Adjusted Growth
from tools.risk_adjusted_growth.quant.data_prep import build_base_table
from tools.risk_adjusted_growth.quant.scoring import compute_scores
# Import logic Market Breadth
from tools.market_breadth.quant.metrics import compute_breadth, top10_by_volume
# Import logic ESR Monitor
from tools.esr_monitor.quant.metrics import calculate_esr

def _get_cache_path(tool_name: str) -> str:
    today_str = date.today().strftime('%d%m%y')
    return DATA_LAKE / "daily_cache" / f"{tool_name}_{today_str}.txt"

def _read_cache(tool_name: str) -> str:
    path = _get_cache_path(tool_name)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None

def _write_cache(tool_name: str, content: str):
    path = _get_cache_path(tool_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def call_kimi(client, system_prompt, user_prompt):
    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=AI_TEMPERATURE
    )
    return response.choices[0].message.content

def run_fear_greed(client, df_stocks):
    cached = _read_cache("feargreed")
    if cached: return cached
    
    metrics_df = calculate_quant_metrics(df_stocks, window_size=60)
    scored_df = calculate_risk_score(metrics_df)
    latest = scored_df.iloc[-1]
    prev = scored_df.iloc[-2]
    score = latest["Risk_Score"]
    date_str = scored_df.index.max().strftime('%d/%m/%Y')
    
    status_text = "EXTREME FEAR" if score <= 20 else "FEAR" if score <= 40 else "NEUTRAL / STOCK PICKING" if score < 60 else "GREED" if score < 80 else "EXTREME GREED"

    with open(str(ROOT_DIR / "promt" / "fear greed promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
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
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("feargreed", res)
    return res

def run_manipulation(client, df_stocks):
    cached = _read_cache("manipulation")
    if cached: return cached
    
    df_prices = prep_mani(df_stocks)
    weights_df, result_df = comp_mani(df_prices, window=60)
    t0_dt = pd.to_datetime("2026-03-02")
    available_dates = result_df.index.date
    if t0_dt.date() not in available_dates:
        t0_dt = pd.to_datetime(available_dates[-1])
    re_df = classify_regime(result_df, threshold=0.15, t0_dt=t0_dt)
    
    date_str = result_df.index.max().strftime('%d/%m/%Y')
    latest = result_df.iloc[-1]

    slope_val = latest["OLS_Slope"]
    slope_pr = latest["PR_Slope"] * 100
    slope_status = "🔴 Cao" if slope_pr >= 80 else "🟢 Thấp" if slope_pr <= 20 else "🟡 Trung bình"

    corr_val = latest["Correlation"]
    corr_pr = latest["PR_Corr"] * 100
    corr_status = "🔴 Rất chặt" if corr_pr >= 80 else "🟢 Phân kỳ" if corr_pr <= 20 else "🟡 Lỏng"

    t0_str = t0_dt.strftime('%d/%m/%Y')
    regime = re_df["Regime"].iloc[-1] if not re_df.empty else "N/A"
    d_corr = re_df["Delta_PR_Corr"].iloc[-1] if not re_df.empty else 0
    d_slope = re_df["Delta_PR_Slope"].iloc[-1] if not re_df.empty else 0

    momentum_str = f"ΔCorr = {d_corr:.2f}, ΔSlope = {d_slope:.2f}"
    
    with open(str(ROOT_DIR / "promt" / "manipulation promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
        
    full_prompt = prompt_template.replace("{date_str}", date_str)\
                                 .replace("{slope_val}", f"{slope_val:.2f}")\
                                 .replace("{slope_pr}", f"{slope_pr:.1f}")\
                                 .replace("{slope_status}", slope_status)\
                                 .replace("{corr_val}", f"{corr_val:.2f}")\
                                 .replace("{corr_pr}", f"{corr_pr:.1f}")\
                                 .replace("{corr_status}", corr_status)\
                                 .replace("{t0_str}", t0_str)\
                                 .replace("{regime}", regime)\
                                 .replace("{momentum_str}", momentum_str)

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("manipulation", res)
    return res

def run_dispersion(client, df_stocks):
    cached = _read_cache("dispersion")
    if cached: return cached
    
    df_idx = load_custom("vnindex_cache.csv")
    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    index_series = df_idx[idx_col]
    
    stock_returns, metrics = calculate_dispersion_metrics(df_stocks, index_series, zscore_type="Rolling", zscore_window=60, dpi_window=60)
    corr = fit_rolling_correlation(stock_returns, window=30, refit_every=5)
    metrics["Ledoit_Correlation"] = corr
    metrics = metrics.dropna(subset=["DPI", "Ledoit_Correlation"])
    
    latest = metrics.iloc[-1]
    date_str = metrics.index.max().strftime('%d/%m/%Y')
    
    spread_val = latest.get("Spread", 0) * 100 * (252**0.5)
    spread_z = latest.get("Spread_Z", 0)
    dpi_val = latest.get("DPI", 0)
    corr_val = latest.get("Ledoit_Correlation", 0)
    
    cs_skew = latest.get("CS_Skewness", "N/A")
    if isinstance(cs_skew, (int, float)) and not pd.isna(cs_skew): cs_skew = f"{cs_skew:+.2f}"
    cs_kurt = latest.get("CS_Kurtosis", "N/A")
    if isinstance(cs_kurt, (int, float)) and not pd.isna(cs_kurt): cs_kurt = f"{cs_kurt:.2f}"

    with open(str(ROOT_DIR / "promt" / "dispersion promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("{date_str}", date_str)\
                                 .replace("{spread_val}", f"{spread_val:.2f}")\
                                 .replace("{spread_z}", f"{spread_z:+.2f}")\
                                 .replace("{dpi_val}", f"{dpi_val:.1f}")\
                                 .replace("{corr_val}", f"{corr_val:.3f}")\
                                 .replace("{cs_skew}", cs_skew)\
                                 .replace("{cs_kurt}", cs_kurt)

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("dispersion", res)
    return res

def run_upside_ratio(client, df_stocks):
    cached = _read_cache("upside_ratio")
    if cached: return cached
    
    data = build_breadth_series(df_stocks, upside_x=2.0, downside_y=-2.0, lookback_days=90)
    up_tuple = run_hybrid_ensemble_mc(data["raw_upside"], days_to_sim=20, num_sims=5000)
    dn_tuple = run_hybrid_ensemble_mc(data["raw_downside"], days_to_sim=20, num_sims=5000)
    
    p5_up, p25_up, p50_up, p75_up, p95_up, phi_up, mu_up, _, _ = up_tuple
    p5_dn, p25_dn, p50_dn, p75_dn, p95_dn, phi_dn, mu_dn, _, _ = dn_tuple
    
    regime_up = (
        "📈 Momentum (Đà Mua)" if phi_up > 0.1
        else "🔄 Mean-reversion (Đảo chiều Mua)" if phi_up < -0.1
        else "🎲 Random Walk (Nhiễu Mua)"
    )
    regime_dn = (
        "🩸 Momentum (Đà Bán)" if phi_dn > 0.1
        else "🔄 Mean-reversion (Đảo chiều Bán)" if phi_dn < -0.1
        else "🎲 Random Walk (Nhiễu Bán)"
    )
    
    with open(str(ROOT_DIR / "promt" / "upside ratio promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    full_prompt = prompt_template.replace("{upside_current}", f"{data['raw_upside'].values[-1]:.2f}")\
                                 .replace("{upside_mu}", f"{mu_up*100:.2f}")\
                                 .replace("{upside_phi}", f"{phi_up:.3f}")\
                                 .replace("{upside_regime}", regime_up)\
                                 .replace("{downside_current}", f"{data['raw_downside'].values[-1]:.2f}")\
                                 .replace("{downside_mu}", f"{mu_dn*100:.2f}")\
                                 .replace("{downside_phi}", f"{phi_dn:.3f}")\
                                 .replace("{downside_regime}", regime_dn)\
                                 .replace("{sim_days}", "19")\
                                 .replace("{p95_up}", f"{p95_up[-1]:.2f}")\
                                 .replace("{p95_dn}", f"{p95_dn[-1]:.2f}")

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("upside_ratio", res)
    return res

def run_risk_adjusted(client, df_stocks):
    cached = _read_cache("risk_adjusted_growth")
    if cached: return cached
    
    # 1. Load & normalize fundamentals
    df_fund = load_custom("bank_fundamentals.csv")
    if "ticker" not in df_fund.columns:
        if df_fund.index.name and str(df_fund.index.name).lower() == "ticker":
            df_fund = df_fund.reset_index()
        elif "Unnamed: 0" in df_fund.columns:
            df_fund = df_fund.rename(columns={"Unnamed: 0": "ticker"})
        else:
            df_fund = df_fund.reset_index().rename(columns={"index": "ticker"})
    
    # 2. Load dividend (optional)
    try:
        df_div = load_custom("dividend_cache.csv")
    except FileNotFoundError:
        df_div = None
    
    # 3. Build base table (tính P/B, payout ratio)
    latest_prices = df_stocks.ffill().iloc[-1]
    df_base = build_base_table(df_fund, df_div, latest_prices)
    
    # 4. Compute scores
    df_result = compute_scores(df_base=df_base, k_value=1.0, coe_decimal=0.14, bvps_change_pct=-5.0, pb_penalty_pct=-5.0)
    
    with open(str(ROOT_DIR / "promt" / "risk adjusted growth promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()

    top_alpha = df_result.nlargest(3, "Economic Alpha")
    top_alpha_str = ", ".join([f"{i+1}. {row['Ngân hàng']} (Alpha {row['Economic Alpha']*100:.1f}%, P/B {row['P/B Gốc']:.2f})" for i, row in enumerate(top_alpha.to_dict('records'))])
    
    bottom_alpha = df_result.nsmallest(3, "Economic Alpha")
    bottom_alpha_str = ", ".join([f"{i+1}. {row['Ngân hàng']} (Alpha {row['Economic Alpha']*100:.1f}%, P/B {row['P/B Gốc']:.2f})" for i, row in enumerate(bottom_alpha.to_dict('records'))])

    full_prompt = prompt_template.replace("{k_scenario}", "Tiêu chuẩn")\
                                 .replace("{k_value}", "1.0")\
                                 .replace("{coe_input}", "14.0")\
                                 .replace("{bvps_change_pct}", "-5.0")\
                                 .replace("{pb_penalty_pct}", "-5.0")\
                                 .replace("{top_alpha_str}", top_alpha_str)\
                                 .replace("{bottom_alpha_str}", bottom_alpha_str)

    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("risk_adjusted_growth", res)
    return res

def run_market_breadth(client, df_stocks):
    cached = _read_cache("market_breadth")
    if cached: return cached
    
    breadth, masks = compute_breadth(df_stocks)
    if breadth.empty:
        return "Không đủ dữ liệu Market Breadth."
    
    latest_date = breadth.index[-1]
    latest = breadth.iloc[-1]
    date_str = latest_date.strftime('%d/%m/%Y')
    total_count = len(masks["> MA20"].loc[latest_date])
    
    ma20_count = int(latest["> MA20"])
    ma20_pct = (ma20_count / total_count * 100.0) if total_count > 0 else 0.0
    ma60_count = int(latest["> MA60"])
    ma60_pct = (ma60_count / total_count * 100.0) if total_count > 0 else 0.0
    ma125_count = int(latest["> MA125"])
    ma125_pct = (ma125_count / total_count * 100.0) if total_count > 0 else 0.0
    ma252_count = int(latest["> MA252"])
    ma252_pct = (ma252_count / total_count * 100.0) if total_count > 0 else 0.0
    
    # Top volume leaders (optional — skip if no volume cache)
    valid_ma20 = masks["> MA20"].loc[latest_date]
    valid_ma20_stocks = valid_ma20[valid_ma20].index
    valid_ma252 = masks["> MA252"].loc[latest_date]
    valid_ma252_stocks = valid_ma252[valid_ma252].index
    
    top_ma20_str = ", ".join(valid_ma20_stocks.tolist()[:10])
    top_ma252_str = ", ".join(valid_ma252_stocks.tolist()[:10])
    
    with open(str(ROOT_DIR / "promt" / "Market Breadth promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template
    full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
    full_prompt = full_prompt.replace("[Nhập số lượng, VD: 215 mã]", f"{total_count} mã")
    full_prompt = full_prompt.replace("Số mã > MA20: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA20: {ma20_count} mã (Chiếm {ma20_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA60: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA60: {ma60_count} mã (Chiếm {ma60_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA125: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA125: {ma125_count} mã (Chiếm {ma125_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("Số mã > MA252: [Nhập số lượng] mã (Chiếm [Nhập tỷ lệ %] rổ)", f"Số mã > MA252: {ma252_count} mã (Chiếm {ma252_pct:.1f}% rổ)")
    full_prompt = full_prompt.replace("[Liệt kê mã, VD: HPG, SSI, NVL, DIG...]", top_ma20_str, 1)
    full_prompt = full_prompt.replace("[Liệt kê mã, VD: VCB, FPT, ACB...]", top_ma252_str, 1)
    
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("market_breadth", res)
    return res

def run_esr_monitor(client, df_stocks):
    cached = _read_cache("esr_monitor")
    if cached: return cached
    
    df_index = load_custom("vnindex_cache.csv")
    df, weights = calculate_esr(df_stocks, df_index, ma_period=125, pca_window=60, bond_yield=0.042)
    
    if df.empty:
        return "Không đủ dữ liệu ESR Monitor."
    
    last = df.iloc[-1]
    date_str = df.index[-1].strftime('%d/%m/%Y')
    index_close = last['INDEX_Close']
    ma_col = "MA125"
    ma_val = last.get(ma_col, 0)
    ma_status = "nằm trên" if index_close >= ma_val else "nằm dưới"
    ssi_pct = last['SSI_Index'] * 100
    status = "SAFE" if last['SSI_Index'] < 0.5 else "WARNING" if last['SSI_Index'] < 0.8 else "CRITICAL"
    
    sorted_w = weights.sort_values(ascending=False)
    w1_name = sorted_w.index[0]
    w1_val = sorted_w.iloc[0] * 100
    w2_name = sorted_w.index[1]
    w2_val = sorted_w.iloc[1] * 100
    w3_name = sorted_w.index[2]
    w3_val = sorted_w.iloc[2] * 100
    
    with open(str(ROOT_DIR / "promt" / "ESR monitor promt.md"), "r", encoding="utf-8") as f:
        prompt_template = f.read()
    
    full_prompt = prompt_template
    full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
    full_prompt = full_prompt.replace("[Nhập điểm số VN30]", f"{index_close:.2f}")
    full_prompt = full_prompt.replace("[nằm trên/nằm dưới]", ma_status)
    full_prompt = full_prompt.replace("[20/60/125/252]", "125")
    full_prompt = full_prompt.replace("[Nhập %, VD: 85.5%]", f"{ssi_pct:.1f}%")
    full_prompt = full_prompt.replace("[SAFE / WARNING / CRITICAL]", status)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w1_name} ({w1_val:.0f}%)", 1)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w2_name} ({w2_val:.0f}%)", 1)
    full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w3_name} ({w3_val:.0f}%)", 1)
    
    parts = full_prompt.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt
    
    res = call_kimi(client, sys_p, usr_p)
    _write_cache("esr_monitor", res)
    return res

def run_executive_summary(api_key: str):
    client = OpenAI(api_key=api_key.strip(), base_url="https://api.moonshot.ai/v1")
    
    df_stocks = load_close_prices()
    
    # Run tools (will use cache if already ran today)
    r1 = run_fear_greed(client, df_stocks)
    r2 = run_manipulation(client, df_stocks)
    r3 = run_dispersion(client, df_stocks)
    r4 = run_upside_ratio(client, df_stocks)
    r5 = run_risk_adjusted(client, df_stocks)
    r6 = run_market_breadth(client, df_stocks)
    r7 = run_esr_monitor(client, df_stocks)
    
    all_reports = (
        f"=== 1. FEAR & GREED ===\n{r1}\n\n"
        f"=== 2. MANIPULATION ===\n{r2}\n\n"
        f"=== 3. DISPERSION ===\n{r3}\n\n"
        f"=== 4. UPSIDE RATIO ===\n{r4}\n\n"
        f"=== 5. RISK ADJUSTED GROWTH ===\n{r5}\n\n"
        f"=== 6. MARKET BREADTH ===\n{r6}\n\n"
        f"=== 7. ESR MONITOR ===\n{r7}"
    )
    
    with open(str(ROOT_DIR / "promt" / "executive_summary_promt.md"), "r", encoding="utf-8") as f:
        master_prompt = f.read()
        
    master_full = master_prompt.replace("{all_reports}", all_reports)
    
    parts = master_full.split("# INPUT DATA")
    sys_p = parts[0].strip()
    usr_p = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else master_full
    
    final_res = call_kimi(client, sys_p, usr_p)
    _write_cache("executive_summary", final_res)
    
    return final_res
