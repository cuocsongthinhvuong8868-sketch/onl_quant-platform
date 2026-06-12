import streamlit as st

from shared.data_loader import load_close_prices
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.risk_adjusted_growth.ui.sidebar import render_sidebar
from tools.risk_adjusted_growth.quant.data_prep import (
    FINANCIAL_REPORT_JSON_DIR,
    STATISTICS_JSON_DIR,
    build_base_table_from_statistics,
    risk_adjusted_growth_source_signature,
)
from tools.risk_adjusted_growth.quant.scoring import compute_scores
from tools.risk_adjusted_growth.ui.charts import render_table, render_alpha_chart
try:
    from config import AI_PROVIDER_MAP
except ImportError:
    AI_PROVIDER_MAP = {
        "kimi-2.6": {
            "display": "Kimi 2.6",
            "api_model": "kimi-k2.6",
            "base_url": "https://api.moonshot.ai/v1",
        },
        "deepseek-v4-pro": {
            "display": "DeepSeek V4 Pro",
            "api_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }


@st.cache_data(show_spinner=False)
def _load_base_data(source_signature: str, price_date: str, price_row: dict):
    return build_base_table_from_statistics(
        STATISTICS_JSON_DIR,
        financial_report_dir=FINANCIAL_REPORT_JSON_DIR,
        price_row=price_row,
    )


def render():
    st.title("Risk-Adjusted Growth Rate")
    st.caption("Economic Alpha cho nhóm ngân hàng, feed từ MozyFin Statistics + BCTC JSON trong data_lake")
    st.caption("Build: RAG JSON feed v2 (ROE/PB từ Statistics, payout từ Cash Flow Dividends paid)")

    params = render_sidebar()
    ai_provider = params["ai_provider"]
    api_key     = params["api_key"]

    try:
        df_close = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    if df_close.empty:
        st.error("market_data.csv rỗng, không thể tính P/B daily.")
        st.stop()

    with st.spinner("Đang tải fundamentals + xây bảng cơ sở..."):
        try:
            source_signature = risk_adjusted_growth_source_signature(
                STATISTICS_JSON_DIR,
                FINANCIAL_REPORT_JSON_DIR,
            )
            price_date = df_close.index.max().strftime("%Y-%m-%d")
            price_row = df_close.ffill().iloc[-1].to_dict()
            df_base = _load_base_data(source_signature, price_date, price_row)
        except (FileNotFoundError, ValueError) as e:
            st.error(str(e))
            st.info(
                "Chạy script:\n"
                "```bash\n"
                "python command/update_risk_adjusted_growth_statistics.py\n"
                "```"
            )
            st.stop()
    data_date = f"{price_date}|{source_signature}"
    source_date = source_signature.split(":", 1)[0]
    st.caption(
        f"📅 Giá daily: {price_date} · Nguồn RAG JSON: {source_date} · "
        f"{len(df_base)} ngân hàng hợp lệ · {STATISTICS_JSON_DIR} + {FINANCIAL_REPORT_JSON_DIR}"
    )

    st.write(
        f"**Viễn cảnh:** {params['selected_k'].split(' ')[0]} | "
        f"**K:** {params['k_value']} | **COE:** {params['coe_input']}% | "
        f"**Kịch bản P/B:** BVPS `{params['bvps_change_pct']}%`, Phạt P/B `{params['pb_penalty_pct']}%`"
    )

    key = {
        "cache_version": 9,
        "source": "statistics_json+financial_report_json",
        "source_signature": source_signature,
        "price_date": price_date,
        "k_value": params["k_value"],
        "coe_decimal": params["coe_decimal"],
        "bvps_change_pct": params["bvps_change_pct"],
        "pb_penalty_pct": params["pb_penalty_pct"],
    }
    force_recompute = st.button("Force Recompute (bỏ cache feed hiện tại)")
    cached = load_daily_cache("risk_adjusted_growth", key, data_date=data_date)
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
        save_daily_cache("risk_adjusted_growth", key, {"df_result": df_result}, data_date=data_date)
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
    
    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])
    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="rag")

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

                            ticker_col = "Ticker" if "Ticker" in df_result.columns else "Ngân hàng"
                            top_alpha = df_result.nlargest(3, "Economic Alpha")
                            top_alpha_str = ", ".join([
                                (
                                    f"{i+1}. {row[ticker_col]} "
                                    f"(Alpha {row['Economic Alpha']*100:.1f}%, "
                                    f"P/B {row['P/B Gốc']:.2f}, "
                                    f"ROE {row['Geomean ROE']*100:.1f}%, "
                                    f"σROE {row['Stdev ROE']*100:.1f}%, "
                                    f"Payout {row['Cash Payout Ratio']*100:.1f}%)"
                                )
                                for i, row in enumerate(top_alpha.to_dict('records'))
                            ])

                            bottom_alpha = df_result.nsmallest(3, "Economic Alpha")
                            bottom_alpha_str = ", ".join([
                                (
                                    f"{i+1}. {row[ticker_col]} "
                                    f"(Alpha {row['Economic Alpha']*100:.1f}%, "
                                    f"P/B {row['P/B Gốc']:.2f}, "
                                    f"ROE {row['Geomean ROE']*100:.1f}%, "
                                    f"σROE {row['Stdev ROE']*100:.1f}%, "
                                    f"Payout {row['Cash Payout Ratio']*100:.1f}%)"
                                )
                                for i, row in enumerate(bottom_alpha.to_dict('records'))
                            ])

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
                                temperature=AI_PROVIDER_MAP[ai_provider].get("temperature", AI_TEMPERATURE)
                            )

                            result_text = response.choices[0].message.content

                            # Lưu cache
                            ai_cache_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(ai_cache_file, "w", encoding="utf-8") as f:
                                f.write(result_text)

                            # Đồng bộ lên GitHub
                            st.success("Hoàn thành phân tích!")
                            with st.container(border=True):
                                st.markdown(result_text)

                        except Exception as e:
                            st.error(f"Lỗi kết nối API: {e}. Vui lòng kiểm tra lại cấu hình thư viện openai và API key!")

    with tab_history:
        from shared.history_selector import build_history_options
        _all_caches = list(DATA_LAKE.glob("daily_cache/risk_adjusted_growth_*.txt"))
        _options = build_history_options(_all_caches, "risk_adjusted_growth", AI_PROVIDER_MAP)
        if not _options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            _selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(_options.keys()),
                index=0,
                key="risk_adjusted_growth_history_selector"
            )
            _sel_path = _options[_selected_label]
            with st.container(border=True):
                try:
                    with open(_sel_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")
