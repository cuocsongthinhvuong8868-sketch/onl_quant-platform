import streamlit as st
import pandas as pd
from datetime import date
from config import DATA_LAKE
from shared.data_loader import load_close_prices, load_custom
from tools.dispersion.quant.metrics import calculate_dispersion_metrics, fit_rolling_correlation, determine_macro_regime
from tools.dispersion.ui.sidebar import render_sidebar
from tools.dispersion.ui.charts import render_main_chart


def _cache_path(params: dict) -> str:
    key = (
        f"mc{params['mc_window']}_rf{params['cov_refit_freq']}_"
        f"z{params['zscore_window']}_dpi{params['dpi_window']}_"
        f"dth{params['dpi_alert_thresh']}_cd{params['corr_dist_thresh']}_"
        f"cc{params['corr_cap_thresh']}"
    ).replace(".", "p")
    return str(DATA_LAKE / f"dispersion_cache_{key}.csv")


def _load_daily_cache(path: str):
    try:
        df = pd.read_csv(path, parse_dates=["time"])
    except Exception:
        return None
    if df.empty or "cache_date" not in df.columns:
        return None
    cache_day = str(df["cache_date"].iloc[0])
    if cache_day != str(date.today()):
        return None
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    if "Macro_Regime" in df.columns:
        df["Macro_Regime"] = df["Macro_Regime"].astype(str)
    return df


def _save_daily_cache(path: str, df_metrics: pd.DataFrame):
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    out = df_metrics.copy()
    out = out.reset_index().rename(columns={"index": "time"})
    out["cache_date"] = str(date.today())
    out.to_csv(path, index=False)


@st.cache_data(show_spinner=False, ttl=86400)
def _compute_metrics_cached(df_prices, index_series, p: dict):
    stock_returns, metrics = calculate_dispersion_metrics(
        df_prices, index_series, p["zscore_window"], p["dpi_window"]
    )
    corr = fit_rolling_correlation(
        stock_returns,
        window=p["mc_window"],
        refit_every=p["cov_refit_freq"],
    )
    metrics["Ledoit_Correlation"] = corr
    metrics["Macro_Regime"] = determine_macro_regime(
        metrics, p["dpi_alert_thresh"], p["corr_dist_thresh"], p["corr_cap_thresh"]
    )
    return metrics.dropna(subset=["DPI", "Ledoit_Correlation"])


def render():
    st.title("Macro Dispersion Radar")
    st.caption("DPI + Systemic Correlation để phát hiện Distribution Peak / Capitulation Bottom")

    p = render_sidebar()
    if p["cov_refit_freq"] <= 1:
        st.warning("Thiết lập `refit Cov = 1` rất nặng với universe lớn. Nên dùng >= 3 để tăng tốc.")

    try:
        df_prices = load_close_prices()
        df_idx = load_custom("vnindex_cache.csv")
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    st.caption(f"📅 Dữ liệu cuối cùng: {df_prices.index.max().strftime('%d/%m/%Y')}")

    idx_col = "VNINDEX" if "VNINDEX" in df_idx.columns else df_idx.columns[0]
    index_series = df_idx[idx_col]
    cache_file = _cache_path(p)

    metrics = _load_daily_cache(cache_file)
    if metrics is not None:
        st.caption(f"⚡ Dùng cache cùng ngày: {cache_file}")
    else:
        with st.spinner("Đang tính Dispersion metrics..."):
            metrics = _compute_metrics_cached(df_prices, index_series, p)
            try:
                _save_daily_cache(cache_file, metrics)
                st.caption(f"💾 Đã tạo cache ngày mới: {cache_file}")
            except Exception as e:
                st.warning(f"Tính xong nhưng không ghi được cache file: {e}")

    if metrics.empty:
        st.warning("Không đủ dữ liệu để tạo tín hiệu dispersion.")
        return

    latest = metrics.iloc[-1]
    regime_map = {
        "NORMAL": "BÌNH THƯỜNG",
        "DISTRIBUTION_PEAK": "PHÂN PHỐI ĐỈNH",
        "CAPITULATION_BOTTOM": "ĐÁY HOẢNG LOẠN",
    }
    c1, c2, c3 = st.columns(3)
    c1.metric("Regime", regime_map.get(latest["Macro_Regime"], latest["Macro_Regime"]))
    c2.metric("DPI", f"{latest['DPI']:.1f}%")
    c3.metric("Ledoit Corr", f"{latest['Ledoit_Correlation']:.3f}")

    render_main_chart(
        metrics,
        dpi_alert_thresh=p["dpi_alert_thresh"],
        corr_dist_thresh=p["corr_dist_thresh"],
        corr_cap_thresh=p["corr_cap_thresh"],
    )
