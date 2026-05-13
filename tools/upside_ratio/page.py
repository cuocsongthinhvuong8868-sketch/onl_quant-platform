import logging

import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.upside_ratio.quant.metrics import build_breadth_series, compute_actual_breadth
from tools.upside_ratio.quant.engine import run_hybrid_ensemble_mc
from tools.upside_ratio.ui.sidebar import render_sidebar
from tools.upside_ratio.ui.charts import render_history_chart, render_projection_tabs, render_diagnostics
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def render():
    st.title("🧬 Hybrid MC Bidirectional Breadth Model")
    st.caption("Upside/Downside breadth ratio với Hybrid Monte Carlo ensemble")

    try:
        df_close = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    try:
        df_index = load_custom("vnindex_cache.csv")
    except FileNotFoundError:
        df_index = None

    params = render_sidebar(df_close=df_close)
    ai_provider = params["ai_provider"]
    api_key     = params["api_key"]

    st.caption(f"📅 Dữ liệu chốt phiên gần nhất: {df_close.index.max().strftime('%d/%m/%Y')}")

    # Cache key phải bao gồm cả backtest_date nếu có
    key = {
        "upside_x": params["upside_x"],
        "downside_y": params["downside_y"],
        "lookback_days": params["lookback_days"],
        "sim_days": params["sim_days"],
        "backtest_date": str(params["backtest_date"]) if params["backtest_date"] else None,
    }

    data_date = df_close.index.max().strftime("%Y-%m-%d")
    cached = load_daily_cache("upside_ratio", key, data_date=data_date)

    if cached is not None:
        data = cached["data"]
        up_tuple = cached["up_tuple"]
        dn_tuple = cached["dn_tuple"]
        actual_up = cached.get("actual_up")
        actual_dn = cached.get("actual_dn")
        st.caption("⚡ Dùng cache cùng ngày (Upside Ratio).")
    else:
        with st.spinner("Đang tính breadth + mô phỏng Monte Carlo..."):
            try:
                data = build_breadth_series(
                    df_close,
                    upside_x=params["upside_x"],
                    downside_y=params["downside_y"],
                    lookback_days=params["lookback_days"],
                    backtest_date=params["backtest_date"],
                )
                up_tuple = run_hybrid_ensemble_mc(
                    data["raw_upside"], days_to_sim=params["sim_days"], num_sims=3000
                )
                dn_tuple = run_hybrid_ensemble_mc(
                    data["raw_downside"], days_to_sim=params["sim_days"], num_sims=3000
                )
            except (ValueError, RuntimeError) as e:
                st.error(f"Lỗi mô hình: {e}")
                st.stop()

        # Tính actual breadth nếu backtest
        actual_up = None
        actual_dn = None
        if params["backtest_date"] is not None and "future_returns" in data:
            actual_up, actual_dn = compute_actual_breadth(
                data["future_returns"],
                data["target_date_pd"],
                params["sim_days"],
                params["upside_x"],
                params["downside_y"],
            )

        payload = {
            "data": data,
            "up_tuple": up_tuple,
            "dn_tuple": dn_tuple,
            "actual_up": actual_up,
            "actual_dn": actual_dn,
        }
        save_daily_cache("upside_ratio", key, payload, data_date=data_date)
        st.caption("💾 Đã tạo cache ngày mới (Upside Ratio).")

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

    a, b, c, d = st.columns(4)
    a.metric("Core Momentum Cầu (φ)", f"{phi_up:.3f}", regime_up)
    b.metric("Long-run Mean Cầu (μ)", f"{mu_up*100:.1f}%")
    c.metric("Core Momentum Cung (φ)", f"{phi_dn:.3f}", regime_dn)
    d.metric("Long-run Mean Cung (μ)", f"{mu_dn*100:.1f}%")

    # Header lịch sử
    header_text = "1. Lịch sử Cung - Cầu & VN-Index"
    if params["backtest_date"] is not None:
        header_text += f" (Góc nhìn từ ngày {params['backtest_date'].strftime('%d/%m/%Y')})"
    st.subheader(header_text)
    render_history_chart(
        data["raw_upside"], data["ma5_upside"],
        data["raw_downside"], data["ma5_downside"],
        mu_up, mu_dn, df_index=df_index,
    )

    st.divider()
    st.subheader(f"2. Dự phóng Monte Carlo — 6.000 kịch bản × {params['sim_days']} phiên")
    resid_up, resid_dn = render_projection_tabs(
        data["raw_upside"], data["ma5_upside"],
        data["raw_downside"], data["ma5_downside"],
        params["sim_days"], up_tuple, dn_tuple,
        actual_up=actual_up, actual_dn=actual_dn,
        backtest_date=params["backtest_date"],
    )

    # Kết luận chi tiết
    current_vs_mu_up = "thấp hơn" if data["raw_upside"].values[-1] < mu_up * 100 else "cao hơn"
    mean_reversion_note_up = (
        "→ Khả năng **hồi phục**" if data["raw_upside"].values[-1] < mu_up * 100
        else "→ Khả năng **điều chỉnh**"
    )

    current_vs_mu_dn = "thấp hơn" if data["raw_downside"].values[-1] < mu_dn * 100 else "cao hơn"
    mean_reversion_note_dn = (
        "→ Khả năng **gia tăng áp lực bán**" if data["raw_downside"].values[-1] < mu_dn * 100
        else "→ Khả năng **hạ nhiệt bán tháo**"
    )

    st.info(
        f"**📈 DỰ PHÓNG LỰC CẦU / UPSIDE (T+{params['sim_days']-1}):**\n\n"
        f"Ensemble Median = **{p50_up[-1]:.1f}%** &nbsp;|&nbsp; "
        f"Dải Core 50%: **{p25_up[-1]:.1f}% – {p75_up[-1]:.1f}%** &nbsp;|&nbsp; "
        f"Dải Rủi ro 90%: **{p5_up[-1]:.1f}% – {p95_up[-1]:.1f}%**\n\n"
        f"Giá trị tính đến ngày chốt **{data['raw_upside'].values[-1]:.1f}%** "
        f"đang {current_vs_mu_up} Long-run mean {mu_up*100:.1f}%. "
        f"{mean_reversion_note_up} về trung bình dài hạn."
    )

    st.error(
        f"**🩸 DỰ PHÓNG LỰC CUNG / DOWNSIDE (T+{params['sim_days']-1}):**\n\n"
        f"Ensemble Median = **{p50_dn[-1]:.1f}%** &nbsp;|&nbsp; "
        f"Dải Core 50%: **{p25_dn[-1]:.1f}% – {p75_dn[-1]:.1f}%** &nbsp;|&nbsp; "
        f"Dải Rủi ro 90%: **{p5_dn[-1]:.1f}% – {p95_dn[-1]:.1f}%**\n\n"
        f"Giá trị tính đến ngày chốt **{data['raw_downside'].values[-1]:.1f}%** "
        f"đang {current_vs_mu_dn} Long-run mean {mu_dn*100:.1f}%. "
        f"{mean_reversion_note_dn} về trung bình dài hạn."
    )

    st.divider()
    st.subheader("✨ Trợ lý AI Quant Phân tích Đa chiều")

    import os
    from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    
    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"upside_ratio_{ai_provider}_{today_str}.txt"
    
    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])
    with tab_current:
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
            btn_label = f"🐺 Phân tích Rủi ro 2 chiều ({AI_PROVIDER_MAP[ai_provider]['display']})"
            if st.button(btn_label, type="primary", use_container_width=True):
                if not api_key:
                    st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                else:
                    with st.spinner("AI đang quét ma trận 12.000 kịch bản Cung - Cầu..."):
                        try:
                            from openai import OpenAI
                            cfg = AI_PROVIDER_MAP[ai_provider]
                            client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
                        
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
                                                         .replace("{sim_days}", str(params['sim_days']-1))\
                                                         .replace("{p95_up}", f"{p95_up[-1]:.2f}")\
                                                         .replace("{p95_dn}", f"{p95_dn[-1]:.2f}")

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

    with tab_history:
        _all_caches = sorted(
            list(DATA_LAKE.glob(f"daily_cache/upside_ratio_*.txt")),
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
                    if "upside_ratio".count("_") > 0:
                        prefix_parts_count = len("upside_ratio".split("_"))
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
                    key="upside_ratio_history_selector"
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


    render_diagnostics(data["raw_upside"], data["raw_downside"], resid_up, resid_dn)