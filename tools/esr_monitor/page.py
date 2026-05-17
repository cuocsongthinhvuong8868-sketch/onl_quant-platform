"""
ESR Monitor — Page layer
=========================
Full 5-pillar Systemic Stress Index (SSI) with HMM regime classifier,
4-state market classification, and AI analysis.
"""
import streamlit as st
from shared.data_loader import load_close_prices, load_custom, load_volumes
from shared.daily_cache import load_daily_cache, save_daily_cache, get_cache_path, clear_daily_cache
from shared.api_key_helper import resolve_api_key
from shared.github_sync import render_sync_button
from tools.esr_monitor.quant.metrics import (
    run_esr_pipeline, SSIResult, MARKET_STATES, VN30_TICKERS,
    PRODUCTION_REGIME_METHOD,
)
from tools.esr_monitor.ui.charts import render_esr_chart, render_pillar_diagnostics
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


def render():
    st.title("🔬 ESR Monitor")
    st.caption(
        "Systemic Stress Index (SSI) cho VN30 — 5 pillar (S_VOL, S_PRES, S_COR, S_LIQ, S_VAL) "
        "kết hợp PCA(1) rank-based + HMM regime classifier + 4-state market matrix."
    )

    # ── Sidebar ──
    ma_period = st.sidebar.slider("VN30 MA Period", 20, 252, 125)
    pca_warmup = st.sidebar.number_input("PCA Warmup (ngày)", value=252, min_value=100, max_value=500, step=10)
    ema_span = st.sidebar.number_input("EMA Smoothing (span)", value=60, min_value=1, max_value=200, step=1)
    deposit_rate = st.sidebar.number_input("Deposit Rate (%)", value=6.0, step=0.1) / 100
    pillar_mode = st.sidebar.radio(
        "Pillar Mode",
        options=['downside', 'classic'],
        index=1,
        help="downside: S_VOL/S_COR/S_LIQ chỉ tính trên phiên giảm. classic: đối xứng.",
    )
    trend_ma_window = st.sidebar.number_input("Trend MA (ngày)", value=200, min_value=50, max_value=500, step=10)
    enable_hmm = st.sidebar.checkbox("Regime Overlay", value=True,
                                     help="Bật/tắt classifier regime (rule-based hoặc HMM).")

    _classifier_options = ['hmm', 'hmm_walk_forward', 'rule_based']
    _default_idx = (_classifier_options.index(PRODUCTION_REGIME_METHOD)
                    if PRODUCTION_REGIME_METHOD in _classifier_options else 0)
    regime_method = st.sidebar.selectbox(
        "Regime Classifier",
        options=_classifier_options,
        index=_default_idx,
        format_func=lambda x: {
            'hmm': '🎯 HMM full-fit (LIVE — detection cao nhất) ⭐ PRODUCTION',
            'hmm_walk_forward': '🧪 HMM walk-forward (look-ahead-free)',
            'rule_based': '📏 Rule-based (percentile rank)',
        }[x],
        help=("HMM full-fit: fit toàn bộ series → có look-ahead bias nhưng OK cho live view "
              "(xem regime hôm nay). Detection chất lượng cao nhất. "
              "HMM walk-forward: refit mỗi 60 ngày, chỉ dùng data trước → look-ahead-free, "
              "dùng cho backtest hoặc history view. "
              "Rule-based: percentile rank + level fallback, không cần hmmlearn."),
    )
    regime_percentile = st.sidebar.slider(
        "Stress percentile threshold", 0.50, 0.90, 0.60, step=0.05,
        help="SSI percentile rank > X → HIGH stress (rule-based only).",
        disabled=(regime_method in ('hmm', 'hmm_walk_forward')),
    )
    regime_abs_threshold = st.sidebar.slider(
        "Absolute SSI threshold (level fallback)", 0.0, 1.0, 0.65, step=0.05,
        help="HIGH stress nếu SSI > X tuyệt đối. Set 0 để tắt (rule-based only).",
        disabled=(regime_method in ('hmm', 'hmm_walk_forward')),
    )
    regime_wf_refit = st.sidebar.slider(
        "HMM walk-forward refit interval (ngày)", 20, 180, 60, step=10,
        help="Số ngày giữa các lần refit HMM walk-forward (chỉ áp dụng cho hmm_walk_forward).",
        disabled=(regime_method != 'hmm_walk_forward'),
    )

    st.sidebar.divider()
    st.sidebar.header("🤖 AI Analysis")
    ai_provider = st.sidebar.selectbox(
        "🤖 Chọn Model AI",
        options=list(AI_PROVIDER_MAP.keys()),
        format_func=lambda k: AI_PROVIDER_MAP[k]["display"],
        index=0,
        key="esr_ai_provider",
    )
    api_key_raw = st.sidebar.text_input("API Key (hoặc shortcut 4 số):", type="password", key="esr_api_key",
        placeholder="sk-... hoặc 4 số",
        help="Gõ API key thật (sk-...) hoặc shortcut 4 số đã lưu trong Streamlit Secrets (VD: 1234)")
    api_key, api_key_msg, api_key_err = resolve_api_key(api_key_raw)
    if api_key_err:
        st.sidebar.error(api_key_msg)
    elif api_key_msg:
        st.sidebar.success(api_key_msg)

            # ── Load data ──
    try:
        df_close = load_close_prices()
        df_vn30 = load_custom("vn30_cache.csv")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    # Volume thật cho S_LIQ (Amihud) — fallback proxy nếu file chưa có
    df_volume = load_volumes()
    has_index_volume = "VN30_volume" in df_vn30.columns
    if df_volume is None or not has_index_volume:
        st.caption(
            "⚠️ Volume thật chưa đầy đủ — S_PRES/S_LIQ đang dùng proxy. "
            "Chạy `python command/update_data.py --backfill 2190` để bổ sung."
        )
    st.caption(f"📅 Dữ liệu cuối: {df_close.index.max().strftime('%d/%m/%Y')}")
    n_vn30 = sum(1 for t in VN30_TICKERS if t in df_close.columns)
    st.caption(f"📊 Số mã VN30: {n_vn30}/30")

    # ── Compute ESR ──
    # Đưa "có volume thật hay không" vào cache key — vì cùng tham số mà đổi
    # nguồn volume sẽ ra pillar khác → không thể chia sẻ cache.
    # s_liq_method bump khi đổi methodology S_LIQ → tự invalidate cache cũ.
    cache_key = {
        "ma_period": ma_period, "pca_warmup": pca_warmup,
        "ema_span": ema_span, "deposit_rate": deposit_rate,
        "pillar_mode": pillar_mode, "trend_ma_window": trend_ma_window,
        "enable_hmm": enable_hmm,
        "regime_method": regime_method,
        "regime_percentile": regime_percentile,
        "regime_abs_threshold": regime_abs_threshold,
        "regime_wf_refit": regime_wf_refit,
        "real_vol": df_volume is not None,
        "real_idx_vol": has_index_volume,
        "s_liq_method": "volume_dryup_v1",
    }
    cached = load_daily_cache("esr_monitor", cache_key)
    if cached is not None:
        pillars = cached["pillars"]
        result = cached["result"]
        market_states = cached.get("market_states")
        threshold = cached.get("threshold")
        st.caption("⚡ Dùng cache cùng ngày (ESR Monitor).")
    else:
        with st.spinner("🔄 Đang tính ESR 5-pillar SSI..."):
            try:
                pillars, result, market_states, threshold = run_esr_pipeline(
                    df_close, df_vn30,
                    df_volume=df_volume,
                    deposit_rate=deposit_rate,
                    pillar_mode=pillar_mode,
                    pca_warmup=pca_warmup,
                    ema_span=ema_span,
                    regime_method=regime_method,
                    regime_percentile=regime_percentile,
                    regime_absolute_threshold=regime_abs_threshold,
                    regime_wf_refit_every=regime_wf_refit,
                )
            except Exception as e:
                st.error(f"Lỗi ESR: {e}")
                st.stop()
        save_daily_cache("esr_monitor", cache_key, {
            "pillars": pillars, "result": result,
            "market_states": market_states, "threshold": threshold,
        })
        st.caption("💾 Đã tạo cache mới (ESR Monitor).")

    # ── Header metrics ──
    last_ssi = result.ssi.dropna().iloc[-1]
    last_evr = result.pca_concentration.dropna().iloc[-1]
    last_idx = pillars['INDEX_Close'].dropna().iloc[-1]

    hmm_ok = enable_hmm and market_states is not None and not market_states.empty
    current_state_key = market_states.dropna().iloc[-1] if hmm_ok else None

    if current_state_key is not None and current_state_key in MARKET_STATES:
        info = MARKET_STATES[current_state_key]
        status, color, bg_color, emoji = info['label'], info['color'], info['bg'], info['emoji']
    elif hmm_ok:
        regime_s = pillars.get('HMM_Regime')
        in_stress = regime_s.dropna().iloc[-1] == 1 if regime_s is not None else False
        status = "HIGH STRESS" if in_stress else "LOW STRESS"
        color = "red" if in_stress else "green"
        bg_color = "#f8f9fa"
        emoji = "🔴" if in_stress else "🟢"
    else:
        status = "SAFE" if last_ssi < 0.5 else ("WARNING" if last_ssi < 0.8 else "CRITICAL")
        color = {"SAFE": "green", "WARNING": "orange", "CRITICAL": "red"}[status]
        bg_color = "#f8f9fa"
        emoji = ""

    extra_parts = []
    if hmm_ok and threshold is not None:
        gap = last_ssi - threshold
        gc = "#c0392b" if gap >= 0 else "#27ae60"
        extra_parts.append(f"HMM thr: <b>{threshold:.3f}</b> | Gap: <span style='color:{gc}'><b>{gap:+.3f}</b></span>")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.markdown(
            f"<div style='padding:15px;border-radius:8px;background:{bg_color};"
            f"border-left:5px solid {color}'>"
            f"<h4 style='margin:0'>Market Regime</h4>"
            f"<h2 style='color:{color};margin:5px 0'>{emoji} {status}</h2>"
            f"<p style='margin:0'>SSI = <b>{last_ssi:.1%}</b></p>"
            f"{'<br>'.join(extra_parts)}</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.metric("PCA Concentration", f"{last_evr:.1%}",
                  help="PC1 EVR — cao = các pillar đồng pha (rủi ro hệ thống)")
        st.metric("VN30 Close", f"{last_idx:,.2f}")
        st.caption(f"⚙️ Pillar mode: **{pillar_mode}**")
        if hmm_ok:
            dist = market_states.dropna().value_counts(normalize=True)
            dist_lines = [
                f"{MARKET_STATES[k]['emoji']} {k.replace('_',' ').title()}: {v:.1%}"
                for k, v in dist.items() if k in MARKET_STATES
            ]
            st.caption("📊 " + " | ".join(dist_lines))
    with c3:
        import plotly.express as px
        last_w = result.weights_history.dropna().iloc[-1]
        fig_w = px.bar(x=last_w.index, y=last_w.values,
                       labels={'x': 'Pillar', 'y': 'Weight'},
                       title="Latest PCA Weights")
        fig_w.update_layout(height=200, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_w, use_container_width=True)
        
        # Giải thích các pillar
        with st.expander("📖 Ý nghĩa các Pillar"):
            st.markdown("""
            | Pillar | Tên đầy đủ | Ý nghĩa |
            |--------|-----------|---------|
            | **S_VOL** | Realized Volatility | Biến động lịch sử 20 ngày của VN30 (cao = stress) |
            | **S_PRES** | Selling Pressure | Tỷ lệ khối lượng giao dịch phiên giảm 5 ngày (cao = áp lực bán mạnh) |
            | **S_COR** | Systemic Correlation | Tương quan hệ thống — PCA(1) giải thích % biến động của 30 mã VN30 (cao = đồng pha, nguy cơ crash) |
            | **S_LIQ** | Illiquidity | Thiếu thanh khoản — Median Amihud 20 ngày (cao = kém thanh khoản) |
            | **S_VAL** | Valuation Tension | Chênh lệch lợi nhuận VN30 1 năm so với lãi suất tiền gửi (thấp = định giá hấp dẫn; âm = thị trường giảm mạnh) |
            """)
            st.caption("📌 **SSI** = tổng hợp có trọng số PCA của 5 pillar trên. Trọng số thay đổi theo thời gian.")

    # ── Main chart ──
    st.subheader("📈 SSI vs VN30")
    render_esr_chart(pillars, result, ma_period=ma_period,
                     trend_ma_window=trend_ma_window,
                     market_states=market_states if enable_hmm else None,
                     threshold=threshold if enable_hmm else None)

        # ── Pillar diagnostics ──
    render_pillar_diagnostics(pillars, result)

    # ── AI Analysis ──
    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Rủi ro Hệ thống")

    import os
    from config import DATA_LAKE, ROOT_DIR
    from datetime import date
    from openai import OpenAI

    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"esr_monitor_{ai_provider}_{today_str}.txt"

    tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])
    with tab_current:
        if ai_cache_file.exists():
            st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
            with open(ai_cache_file, "r", encoding="utf-8") as f:
                cached_result = f.read()
            with st.container(border=True):
                st.markdown(cached_result)

            from shared.github_sync import render_sync_button
            render_sync_button(ai_cache_file, key_suffix="esr_monitor")

            if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="esr_rerun_ai"):
                os.remove(ai_cache_file)
                st.rerun()
        else:
            btn_label = f"🐺 Phân tích ESR Rủi ro Hệ thống ({AI_PROVIDER_MAP[ai_provider]['display']})"
            if st.button(btn_label, type="primary", use_container_width=True, key="esr_run_ai"):
                if not api_key:
                    st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
                else:
                    with st.spinner("AI đang phân tích rủi ro hệ thống và phân rã PCA..."):
                        try:
                            cfg = AI_PROVIDER_MAP[ai_provider]
                            client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])

                            with open(str(ROOT_DIR / "promt" / "ESR monitor promt.md"), "r", encoding="utf-8") as f:
                                prompt_template = f.read()

                            # Thu thập dữ liệu
                            date_str = pillars.index[-1].strftime('%d/%m/%Y')
                            index_close = pillars['INDEX_Close'].dropna().iloc[-1]
                            ssi_pct = last_ssi * 100
                            evr_pct = last_evr * 100

                            # PCA weights top 3
                            last_w = result.weights_history.dropna().iloc[-1]
                            sorted_w = last_w.sort_values(ascending=False)
                            w1_name = sorted_w.index[0]
                            w1_val = sorted_w.iloc[0] * 100
                            w2_name = sorted_w.index[1]
                            w2_val = sorted_w.iloc[1] * 100
                            w3_name = sorted_w.index[2]
                            w3_val = sorted_w.iloc[2] * 100

                            # Market state info
                            if hmm_ok and current_state_key is not None:
                                state_info_str = f"{MARKET_STATES[current_state_key]['label']}: {MARKET_STATES[current_state_key]['description']}"
                            elif hmm_ok:
                                state_info_str = status
                            else:
                                state_info_str = status

                            # Replace placeholders
                            full_prompt = prompt_template
                            full_prompt = full_prompt.replace("[Nhập ngày, VD: 09/05/2026]", date_str)
                            full_prompt = full_prompt.replace("[Nhập điểm số VN30]", f"{index_close:.2f}")
                            full_prompt = full_prompt.replace("[nằm trên/nằm dưới]",
                                "nằm trên" if index_close >= pillars['INDEX_Close'].rolling(ma_period).mean().iloc[-1] else "nằm dưới")
                            full_prompt = full_prompt.replace("[20/60/125/252]", str(ma_period))
                            full_prompt = full_prompt.replace("[Nhập %, VD: 85.5%]", f"{ssi_pct:.1f}%")
                            full_prompt = full_prompt.replace("[SAFE / WARNING / CRITICAL]", status)
                            full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w1_name} ({w1_val:.0f}%)", 1)
                            full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w2_name} ({w2_val:.0f}%)", 1)
                            full_prompt = full_prompt.replace("[Tên Pillar, VD: S_COR (35%)]", f"{w3_name} ({w3_val:.0f}%)", 1)
                            # Extended fields
                            full_prompt = full_prompt.replace("[PCA_EVR]", f"{evr_pct:.1f}%")
                            full_prompt = full_prompt.replace("[Market State]", state_info_str)
                            full_prompt = full_prompt.replace("[Pillar Mode]", pillar_mode)

                            parts = full_prompt.split("# INPUT DATA")
                            system_prompt = parts[0].strip()
                            user_prompt = "# INPUT DATA" + parts[1].strip() if len(parts) > 1 else full_prompt

                            temperature = cfg.get("temperature", 1.0)

                            response = client.chat.completions.create(
                                model=cfg["api_model"],
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ],
                                temperature=temperature
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
        from shared.history_selector import build_history_options
        _all_caches = list(DATA_LAKE.glob("daily_cache/esr_monitor_*.txt"))
        _options = build_history_options(_all_caches, "esr_monitor", AI_PROVIDER_MAP)
        if not _options:
            st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
        else:
            _selected_label = st.selectbox(
                "📅 Chọn ngày và model:",
                options=list(_options.keys()),
                index=0,
                key="esr_monitor_history_selector"
            )
            _sel_path = _options[_selected_label]
            with st.container(border=True):
                try:
                    with open(_sel_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")

