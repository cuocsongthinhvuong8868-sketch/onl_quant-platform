import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.risk_adjusted_growth.ui.sidebar import render_sidebar
from tools.risk_adjusted_growth.quant.data_prep import build_base_table
from tools.risk_adjusted_growth.quant.scoring import compute_scores
from tools.risk_adjusted_growth.ui.charts import render_table, render_alpha_chart


@st.cache_data(show_spinner=False)
def _load_base_data(df_close):
    df_fund = load_custom("bank_fundamentals.csv")
    try:
        df_div = load_custom("dividend_cache.csv")
    except FileNotFoundError:
        df_div = None

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

    params = render_sidebar()

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
        "k_value": params["k_value"],
        "coe_decimal": params["coe_decimal"],
        "bvps_change_pct": params["bvps_change_pct"],
        "pb_penalty_pct": params["pb_penalty_pct"],
    }
    cached = load_daily_cache("risk_adjusted_growth", key)
    if cached is not None:
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
