import pandas as pd


def build_breadth_series(
    df_close: pd.DataFrame,
    upside_x: float,
    downside_y: float,
    lookback_days: int,
    backtest_date=None,
):
    """Tính Upside/Downside breadth ratio từ giá đóng cửa.

    Parameters
    ----------
    backtest_date : date-like, optional
        Nếu có, dữ liệu train sẽ cắt đến ngày này; trả về thêm future_returns
        để vẽ overlay thực tế trong chế độ backtest.
    """
    returns = df_close.pct_change() * 100.0
    returns = returns.dropna(how="all")
    returns = returns.loc[returns.abs().sum(axis=1) > 0.001]

    if backtest_date is not None:
        target_date_pd = pd.to_datetime(backtest_date)
        train_returns = returns.loc[:target_date_pd].tail(lookback_days + 10)
        future_returns = returns.loc[:].copy()
    else:
        train_returns = returns.tail(lookback_days + 10)
        future_returns = pd.DataFrame()

    total_valid = train_returns.notna().sum(axis=1)

    upside_counts = (train_returns > upside_x).sum(axis=1)
    raw_upside = (upside_counts / total_valid) * 100.0
    ma5_upside = raw_upside.rolling(window=5).mean().dropna().tail(lookback_days)
    raw_upside = raw_upside.loc[ma5_upside.index]

    downside_counts = (train_returns < downside_y).sum(axis=1)
    raw_downside = (downside_counts / total_valid) * 100.0
    ma5_downside = raw_downside.rolling(window=5).mean().dropna().tail(lookback_days)
    raw_downside = raw_downside.loc[ma5_downside.index]

    if len(raw_upside) < 30 or len(raw_downside) < 30:
        raise ValueError("Không đủ dữ liệu lịch sử sau lọc để chạy mô hình.")

    result = {
        "returns": returns,
        "raw_upside": raw_upside,
        "ma5_upside": ma5_upside,
        "raw_downside": raw_downside,
        "ma5_downside": ma5_downside,
    }

    if backtest_date is not None:
        result["future_returns"] = future_returns
        result["target_date_pd"] = target_date_pd

    return result


def compute_actual_breadth(future_returns, target_date_pd, sim_days, user_X, user_Y):
    """Tính actual upside/downside MA5 từ future_returns cho backtest overlay."""
    try:
        target_idx = future_returns.index.get_loc(target_date_pd)
        actual_future = future_returns.iloc[target_idx - 4 : target_idx + sim_days + 1]

        total_valid = actual_future.notna().sum(axis=1)
        upside_counts = (actual_future > user_X).sum(axis=1)
        raw_up = (upside_counts / total_valid) * 100.0
        ma5_up = raw_up.rolling(window=5).mean().dropna()

        downside_counts = (actual_future < user_Y).sum(axis=1)
        raw_dn = (downside_counts / total_valid) * 100.0
        ma5_dn = raw_dn.rolling(window=5).mean().dropna()

        return ma5_up, ma5_dn
    except KeyError:
        return None, None
