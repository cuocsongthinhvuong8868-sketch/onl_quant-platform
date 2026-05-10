import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.risk_adjusted_growth.ui.sidebar import render_sidebar
from tools.risk_adjusted_growth.quant.data_prep import build_base_table
from tools.risk_adjusted_growth.quant.scoring import compute_scores
from tools.risk_adjusted_growth.ui.charts import render_table, render_alpha_chart
from config import AI_PROVIDER_MAP


@st.cache_data(show_spinner=False)
def _load_base_data(df_close):
    df_fund = load_custom("bank_fundamentals.csv")
    try:
        df_div = load_custom("dividend_cache.csv")
    except FileNotFoundError:
        df_div = None

    # load_custom dùng index_col=0, nên dividend có thể bị đẩy mã cổ phiếu vào index.
    if df_div is not None and not df_div.empty:
        div_cols = {str(c) for c in df_div.columns}
        has_symbol_col = ("Ma CP" in div_cols) or ("ticker" in div_cols)
        if not has_symbol_col:
            if df_div.index.name:
                idx_name = str(df_div.index.name)
                if idx_name.lower() == "ma cp":
                    df_div = df_div.reset_index().rename(columns={idx_name: "Ma CP"})
                elif idx_name.lower() == "ticker":
                    df_div = df_div.reset_index().rename(columns={idx_name: "ticker"})
                else:
                    df_div = df_div.reset_index().rename(columns={"index": "ticker"})
            else:
                df_div = df_div.reset_index().rename(columns={"index": "ticker"})

    # load_custom dùng index_col=0, nên CSV fundamentals có thể bị đẩy ticker vào index.
    if "ticker" not in df_fund.columns:
        if df_fund.index.name and str(df_fund.index.name).lower() == "ticker":
            df_fund = df_fund.reset_index()
        elif "Unnamed: 0" in df_fund.columns:
            df_fund = df_fund.rename(columns={"Unnamed: 0": "ticker"})
        else:
            df_fund = df_fund.reset_index().rename(columns={"index": "ticker"})

    if "ticker" not in df_fund.columns:
        raise ValueError("bank_fundamentals.csv thiếu cột 'ticker'.")

    if df_close.empty:
        raise ValueError("market_data.csv rỗng, chưa có dữ liệu giá.")

    latest_prices = df_close.ffill().iloc[-1]
    return build_base_table(df_fund, df_div, latest_prices)


def render():
    st.title("Risk-Adjusted Growth Rate")
    st.caption("Economic Alpha cho nhóm ngân hàng, tách quant/UI theo pipeline data_lake")
    st.caption("Build: RAG fix v3 (PB unit-normalized + dividend index normalization)")

    params = render_sidebar()
    ai_provider = params["ai_provider"]
    api_key     = params["api_key"]

    try:
        df_close = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_close.index.max().strftime('%d/%m/%Y')}")

    with st.spinner("Đang tải fundamentals + xây bảng cơ sở..."):
        try:
            df_base = _load_base_data(df_close)
        except (FileNotFoundError, ValueError) as e:
            st.error(str(e))
            st.info("Chạy script `python3 update_bank_fundamentals.py` để tạo dữ liệu fundamentals trong data_lake.")
            st.stop()

    st.write(
        f"**Viễn cảnh:** {params['selected_k'].split(' ')[0]} | "
        f"**K:** {params['k_value']} | **COE:** {params['coe_input']}% | "
        f"**Kịch bản P/B:** BVPS `{params['bvps_change_pct']}%`, Phạt P/B `{params['pb_penalty_pct']}%`"
    )

    key = {
        "cache_version": 3,
        "k_value": params["k_value"],
        "coe_decimal": params["coe_decimal"],
        "bvps_change_pct": params["bvps_change_pct"],
        "pb_penalty_pct": params["pb_penalty_pct"],
    }
    force_recompute = st.button("Force Recompute (bỏ cache hôm nay)")
    cached = load_daily_cache("risk_adjusted_growth", key)
    if (cached is not None) and (not force_recompute):
        df_result = cached["df_result"]
        st.caption("⚡ Dùng cache cùng ngày (Risk-Adjusted Growth).")
    else:
        df_result = compute_scores(
            df_base=df_base,
            k_value=params["k_value"],
            coe_decimal=params["coe_decimal"],
            bvps_change_pct=params["bvps_change_pct"],
            pb_penalty_pct=params["pb_penalty_pct"],
        )
        save_daily_cache("risk_adjusted_growth", key, {"df_result": df_result})
        st.caption("💾 Đã tạo cache ngày mới (Risk-Adjusted Growth).")

    render_table(df_result)
    render_alpha_chart(df_result)

    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Cấu trúc Ngành")

    import os
    from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    
    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"risk_adjusted_growth_{ai_provider}_{today_str}.txt"
    
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
        btn_label = f"🐺 Phân tích Economic Alpha ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang phân tích cấu trúc rủi ro và lợi nhuận..."):
                    try:
                        from openai import OpenAI
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
                        
                        with open(str(ROOT_DIR / "promt" / "risk adjusted growth promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()
    
                        top_alpha = df_result.nlargest(3, "Economic Alpha")
                        top_alpha_str = ", ".join([f"{i+1}. {row['Ngân hàng']} (Alpha {row['Economic Alpha']*100:.1f}%, P/B {row['P/B Gốc']:.2f})" for i, row in enumerate(top_alpha.to_dict('records'))])
                        
                        bottom_alpha = df_result.nsmallest(3, "Economic Alpha")
                        bottom_alpha_str = ", ".join([f"{i+1}. {row['Ngân hàng']} (Alpha {row['Economic Alpha']*100:.1f}%, P/B {row['P/B Gốc']:.2f})" for i, row in enumerate(bottom_alpha.to_dict('records'))])

                        full_prompt = prompt_template.replace("{k_scenario}", params['selected_k'].split(' ')[0])\
                                                     .replace("{k_value}", str(params['k_value']))\
                                                     .replace("{coe_input}", str(params['coe_input']))\
                                                     .replace("{bvps_change_pct}", str(params['bvps_change_pct']))\
                                                     .replace("{pb_penalty_pct}", str(params['pb_penalty_pct']))\
                                                     .replace("{top_alpha_str}", top_alpha_str)\
                                                     .replace("{bottom_alpha_str}", bottom_alpha_str)

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
