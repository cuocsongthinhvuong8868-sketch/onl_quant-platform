import pandas as pd
import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.market_breadth.quant.metrics import compute_breadth, top10_by_volume
from tools.market_breadth.ui.sidebar import render_sidebar
from tools.market_breadth.ui.charts import render_breadth_chart
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
def _load_optional_volume_cache() -> pd.DataFrame | None:
    try:
        df = load_custom("market_breadth_cache.csv")
    except FileNotFoundError:
        return None

    # load_custom(index_col=0) giữ được index thời gian, columns dạng XXX_close / XXX_volume
    vol = df.filter(regex="_volume$").rename(columns=lambda c: c.replace("_volume", ""))
    if vol.empty:
        return None
    return vol.sort_index().fillna(0)


def render():
    st.title("Market Breadth")
    st.caption("Độ rộng thị trường: số mã nằm trên MA20/60/125/252")

    try:
        df_prices = load_close_prices()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_prices.index.max().strftime('%d/%m/%Y')}")

    if df_prices.empty:
        st.error("market_data.csv rỗng.")
        st.stop()

    df_volumes = _load_optional_volume_cache()

    key = {"universe_cols": int(df_prices.shape[1])}
    cached = load_daily_cache("market_breadth", key)
    if cached is not None:
        breadth = cached["breadth"]
        masks = cached["masks"]
        st.caption("⚡ Dùng cache cùng ngày (Market Breadth).")
    else:
        breadth, masks = compute_breadth(df_prices)
        save_daily_cache("market_breadth", key, {"breadth": breadth, "masks": masks})
        st.caption("💾 Đã tạo cache ngày mới (Market Breadth).")
    if breadth.empty:
        st.warning("Không đủ dữ liệu để tính Market Breadth.")
        st.stop()

    if breadth.index.tz is not None:
        breadth.index = breadth.index.tz_localize(None)

    start_date, end_date, start_dt, end_dt, ai_provider, api_key = render_sidebar(breadth)
    df_plot = breadth[(breadth.index >= start_dt) & (breadth.index <= end_dt)]

    if df_plot.empty:
        st.warning("Không có dữ liệu trong khoảng thời gian đã chọn.")
        return

    render_breadth_chart(df_plot, start_date, end_date)

    latest_date = df_plot.index[-1]
    latest = df_plot.iloc[-1]

    st.subheader(f"Dữ liệu Market Breadth cuối kỳ ({latest_date.strftime('%d/%m/%Y')})")

    cols = st.columns(4)
    for i, bucket in enumerate(["> MA20", "> MA60", "> MA125", "> MA252"]):
        with cols[i]:
            valid = masks[bucket].loc[latest_date]
            total = len(valid)
            count = int(latest[bucket])
            pct = (count / total * 100.0) if total > 0 else 0.0
            st.metric(f"Cổ phiếu {bucket}", f"{count} ({pct:.1f}%)")
            valid_stocks = valid[valid].index
            with st.popover("Xem Top 10 Khối Lượng"):
                top_df = top10_by_volume(df_volumes, latest_date, valid_stocks)
                if top_df.empty:
                    st.caption("Chưa có volume cache cho ngày này.")
                else:
                    st.dataframe(top_df, hide_index=True)

    # ── AI Analysis ──
    st.divider()
    st.subheader("✨ Trợ lý AI Phân tích Độ rộng Thị trường")

    import os
    from config import DATA_LAKE, AI_TEMPERATURE, ROOT_DIR
    from datetime import date
    from openai import OpenAI

    today_str = date.today().strftime('%d%m%y')
    ai_cache_file = DATA_LAKE / "daily_cache" / f"market_breadth_{ai_provider}_{today_str}.txt"

    if ai_cache_file.exists():
        st.success("Tải kết quả AI từ bộ nhớ tạm (Cache ngày)!")
        with open(ai_cache_file, "r", encoding="utf-8") as f:
            cached_result = f.read()
        with st.container(border=True):
            st.markdown(cached_result)

        if st.button("🔄 Chạy lại phân tích AI", type="secondary", key="mb_rerun_ai"):
            os.remove(ai_cache_file)
            st.rerun()
    else:
        btn_label = f"🐺 Phân tích Độ rộng Thị trường ({AI_PROVIDER_MAP[ai_provider]['display']})"
        if st.button(btn_label, type="primary", use_container_width=True, key="mb_run_ai"):
            if not api_key:
                st.error("⚠️ Bạn chưa nhập API Key ở thanh menu bên trái.")
            else:
                with st.spinner("AI đang phân tích cấu trúc độ rộng và dòng tiền..."):
                    try:
                        cfg = AI_PROVIDER_MAP[ai_provider]
                        client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])

                        with open(str(ROOT_DIR / "promt" / "Market Breadth promt.md"), "r", encoding="utf-8") as f:
                            prompt_template = f.read()

                        # Thu thập dữ liệu
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

                        # Top volume leaders
                        valid_ma20 = masks["> MA20"].loc[latest_date]
                        valid_ma20_stocks = valid_ma20[valid_ma20].index
                        top_ma20_df = top10_by_volume(df_volumes, latest_date, valid_ma20_stocks)
                        top_ma20_str = ", ".join(top_ma20_df["Mã CP"].tolist()) if not top_ma20_df.empty else "Không có dữ liệu khối lượng"

                        valid_ma252 = masks["> MA252"].loc[latest_date]
                        valid_ma252_stocks = valid_ma252[valid_ma252].index
                        top_ma252_df = top10_by_volume(df_volumes, latest_date, valid_ma252_stocks)
                        top_ma252_str = ", ".join(top_ma252_df["Mã CP"].tolist()) if not top_ma252_df.empty else "Không có dữ liệu khối lượng"

                        # Replace placeholders trong prompt
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