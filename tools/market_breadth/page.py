import pandas as pd
import streamlit as st

from shared.data_loader import load_close_prices, load_custom
from shared.daily_cache import load_daily_cache, save_daily_cache
from tools.market_breadth.quant.metrics import compute_breadth, top10_by_volume
from tools.market_breadth.ui.sidebar import render_sidebar
from tools.market_breadth.ui.charts import render_breadth_chart


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

    start_date, end_date, start_dt, end_dt = render_sidebar(breadth)
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
            st.metric(f"Cổ phiếu {bucket}", f"{int(latest[bucket])}")
            valid = masks[bucket].loc[latest_date]
            valid_stocks = valid[valid].index
            with st.popover("Xem Top 10 Khối Lượng"):
                top_df = top10_by_volume(df_volumes, latest_date, valid_stocks)
                if top_df.empty:
                    st.caption("Chưa có volume cache cho ngày này.")
                else:
                    st.dataframe(top_df, hide_index=True)
