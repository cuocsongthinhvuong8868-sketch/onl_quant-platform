import pandas as pd

METHOD_VERSION = "upside_ratio_v2.0.0"


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
    returns = df_close.pct_change(fill_method=None) * 100.0
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


def summarize_breadth_state(data: dict[str, pd.Series]) -> dict[str, float | str]:
    """Summarize latest upside/downside participation into auditable stress fields.

    High score means downside participation dominates upside participation.
    The function only uses the already cut training window, so it is safe for
    as-of/backtest views.
    """
    raw_upside = data["raw_upside"].dropna()
    raw_downside = data["raw_downside"].dropna()
    ma5_upside = data["ma5_upside"].dropna()
    ma5_downside = data["ma5_downside"].dropna()
    if raw_upside.empty or raw_downside.empty or ma5_upside.empty or ma5_downside.empty:
        raise ValueError("Không đủ dữ liệu breadth để tạo summary.")

    upside_current = float(raw_upside.iloc[-1])
    downside_current = float(raw_downside.iloc[-1])
    upside_ma5 = float(ma5_upside.iloc[-1])
    downside_ma5 = float(ma5_downside.iloc[-1])
    upside_rank = float(raw_upside.rank(pct=True).iloc[-1])
    downside_rank = float(raw_downside.rank(pct=True).iloc[-1])
    net_pressure = downside_current - upside_current
    ma5_net_pressure = downside_ma5 - upside_ma5

    ma5_pressure_norm = max(0.0, min(ma5_net_pressure / 50.0, 1.0))
    low_upside_norm = 1.0 - upside_rank
    breadth_stress_score = max(
        0.0,
        min(
            100.0,
            55.0 * downside_rank + 30.0 * ma5_pressure_norm + 15.0 * low_upside_norm,
        ),
    )

    if downside_current >= 50.0 or downside_ma5 >= 35.0:
        regime = "CAPITULATION_BREADTH"
    elif downside_rank >= 0.90 and net_pressure >= 15.0:
        regime = "DOWNSIDE_STRESS"
    elif ma5_net_pressure >= 15.0 and downside_ma5 >= 20.0:
        regime = "PERSISTENT_SELL_PRESSURE"
    elif upside_rank >= 0.90 and -net_pressure >= 15.0:
        regime = "UPSIDE_EXPANSION"
    elif downside_current > upside_current:
        regime = "SELL_PRESSURE"
    elif upside_current > downside_current:
        regime = "BUY_PRESSURE"
    else:
        regime = "BALANCED"

    if breadth_stress_score >= 80.0:
        stress_level = "EXTREME"
    elif breadth_stress_score >= 65.0:
        stress_level = "HIGH"
    elif breadth_stress_score >= 45.0:
        stress_level = "ELEVATED"
    else:
        stress_level = "NORMAL"

    return {
        "methodology_version": METHOD_VERSION,
        "upside_rank": upside_rank,
        "downside_rank": downside_rank,
        "upside_ma5": upside_ma5,
        "downside_ma5": downside_ma5,
        "net_pressure": net_pressure,
        "ma5_net_pressure": ma5_net_pressure,
        "breadth_stress_score": breadth_stress_score,
        "breadth_stress_level": stress_level,
        "breadth_regime": regime,
    }


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
