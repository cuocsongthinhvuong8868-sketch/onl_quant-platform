import pandas as pd


def build_breadth_series(df_close: pd.DataFrame, upside_x: float, downside_y: float, lookback_days: int):
    returns = df_close.pct_change() * 100.0
    returns = returns.dropna(how="all")
    returns = returns.loc[returns.abs().sum(axis=1) > 0.001]

    train_returns = returns.tail(lookback_days + 10)
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

    return {
        "returns": returns,
        "raw_upside": raw_upside,
        "ma5_upside": ma5_upside,
        "raw_downside": raw_downside,
        "ma5_downside": ma5_downside,
    }
