import os
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["time", "ticker", "open", "high", "low", "close", "volume"]


def _cache_path(market_data_folder: str) -> Path:
    return Path(market_data_folder) / "bank_ohlcv_cache.csv"


def load_cached_ohlcv(market_data_folder: str) -> pd.DataFrame:
    path = _cache_path(market_data_folder)
    if not path.exists():
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    df = pd.read_csv(path)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df


def save_ohlcv_cache(df: pd.DataFrame, market_data_folder: str) -> None:
    path = _cache_path(market_data_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False)


def fetch_vnstock_ohlcv(
    tickers: Iterable[str],
    market_data_folder: str,
    lookback_days: int = 730,
    sleep_seconds: float = 0.25,
    source: str = "VCI",
) -> pd.DataFrame:
    """
    Fetch daily OHLCV from vnstock using the same Quote.history pattern as
    the market_breadth reference app, then cache one long table locally.
    """
    try:
        from vnstock import Quote
    except ImportError as exc:
        raise RuntimeError("vnstock is not installed. Run: pip install -U vnstock") from exc

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    frames = []

    for ticker in sorted({str(t).upper().strip() for t in tickers if str(t).strip()}):
        try:
            quote = Quote(symbol=ticker, source=source)
            raw = quote.history(start=start_date, end=end_date, interval="1D")
            if raw is None or raw.empty:
                continue

            raw.columns = raw.columns.str.lower()
            if "time" not in raw.columns or "close" not in raw.columns:
                continue

            frame = raw.copy()
            for col in ["open", "high", "low", "close", "volume"]:
                if col not in frame.columns:
                    frame[col] = pd.NA

            frame = frame[["time", "open", "high", "low", "close", "volume"]].copy()
            frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
            frame["ticker"] = ticker
            frames.append(frame[OHLCV_COLUMNS])
            time.sleep(sleep_seconds)
        except Exception:
            logger.exception("Failed to fetch OHLCV for ticker=%s using source=%s", ticker, source)
            continue

    if not frames:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["time", "ticker", "close"])
    df = df.sort_values(["ticker", "time"])
    save_ohlcv_cache(df, market_data_folder)
    return df


def get_ohlcv(
    tickers: Iterable[str],
    market_data_folder: str,
    refresh: bool = False,
    fetch_if_missing: bool = True,
) -> tuple[pd.DataFrame, str]:
    cached = load_cached_ohlcv(market_data_folder)
    if not refresh and not cached.empty:
        return cached, "cache"

    if refresh or fetch_if_missing:
        fetched = fetch_vnstock_ohlcv(tickers, market_data_folder)
        if not fetched.empty:
            return fetched, "vnstock"

    return cached, "cache" if not cached.empty else "none"


def _score_return(value: float, strong: float, weak: float) -> float:
    if pd.isna(value):
        return 0.0
    if value >= strong:
        return 1.0
    if value <= weak:
        return 0.0
    return (value - weak) / (strong - weak)


def _technical_snapshot(group: pd.DataFrame) -> dict:
    group = group.sort_values("time").copy()
    group["close"] = pd.to_numeric(group["close"], errors="coerce")
    group["volume"] = pd.to_numeric(group["volume"], errors="coerce")
    group = group.dropna(subset=["close"])
    if group.empty:
        return {}

    close = group["close"]
    volume = group["volume"]
    latest = group.iloc[-1]

    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma125 = close.rolling(125).mean().iloc[-1]
    ma252 = close.rolling(252).mean().iloc[-1]
    latest_close = float(latest["close"])

    ret20 = latest_close / close.shift(20).iloc[-1] - 1 if len(close) > 20 else float("nan")
    ret60 = latest_close / close.shift(60).iloc[-1] - 1 if len(close) > 60 else float("nan")
    ret125 = latest_close / close.shift(125).iloc[-1] - 1 if len(close) > 125 else float("nan")
    high60 = close.tail(60).max()
    drawdown60 = latest_close / high60 - 1 if pd.notna(high60) and high60 > 0 else float("nan")
    avg_volume20 = volume.tail(20).mean()
    volume_ratio = latest["volume"] / avg_volume20 if pd.notna(avg_volume20) and avg_volume20 > 0 else float("nan")

    above_ma20 = pd.notna(ma20) and latest_close > ma20
    above_ma60 = pd.notna(ma60) and latest_close > ma60
    above_ma125 = pd.notna(ma125) and latest_close > ma125
    above_ma252 = pd.notna(ma252) and latest_close > ma252

    trend_score = (
        (15 if above_ma20 else 0)
        + (15 if above_ma60 else 0)
        + (10 if above_ma125 else 0)
        + (5 if above_ma252 else 0)
    )
    momentum_score = 20 * _score_return(ret20, 0.08, -0.05) + 15 * _score_return(ret60, 0.12, -0.08)
    volume_score = 10 * _score_return(volume_ratio, 1.5, 0.6)
    drawdown_score = 10 * _score_return(drawdown60, -0.03, -0.20)
    score = max(0.0, min(100.0, trend_score + momentum_score + volume_score + drawdown_score))

    return {
        "ticker": latest["ticker"],
        "market_data_date": latest["time"],
        "market_close": latest_close,
        "ma20": ma20,
        "ma60": ma60,
        "ma125": ma125,
        "ma252": ma252,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "above_ma125": above_ma125,
        "above_ma252": above_ma252,
        "return_20d": ret20,
        "return_60d": ret60,
        "return_125d": ret125,
        "volume_ratio_20d": volume_ratio,
        "drawdown_60d": drawdown60,
        "market_confirmation_score": score,
    }


def _alignment_score(gap: float) -> float:
    if pd.isna(gap):
        return float("nan")
    abs_gap = abs(gap)
    if abs_gap <= 0.05:
        return 100.0
    if abs_gap <= 0.10:
        return 80.0
    if abs_gap <= 0.20:
        return 50.0
    return 20.0


def _confirmation_label(row: pd.Series) -> str:
    cls = row.get("classification", "")
    score = row.get("market_confirmation_score", float("nan"))
    gap = row.get("valuation_gap_pct", float("nan"))

    if pd.isna(score):
        return "No Market Data"

    if cls in {"Strong Undervalued", "Undervalued but Risky"}:
        if score >= 65:
            return "Undervalued, Price Confirmed"
        if score >= 45:
            return "Early Confirmation"
        return "Unconfirmed Undervalued"

    if cls == "Fairly Valued":
        if not pd.isna(gap) and abs(gap) <= 0.10 and score >= 45:
            return "Fair Value, Market Agrees"
        if score < 35:
            return "Fair, Weak Price Action"
        return "Neutral Confirmation"

    if cls == "Overvalued":
        if score >= 65:
            return "Overpriced but Momentum Supported"
        if score < 35:
            return "Overpriced and Weak"
        return "Overvalued, Mixed Tape"

    if cls == "Value Trap Warning":
        return "Value Trap Tape"

    return "Neutral Confirmation"


def calculate_market_confirmation(valuation_df: pd.DataFrame, ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    if valuation_df.empty:
        return valuation_df.copy()

    result = valuation_df.copy()
    if ohlcv_df.empty:
        result["market_confirmation_score"] = float("nan")
        result["valuation_alignment_score"] = result["valuation_gap_pct"].apply(_alignment_score)
        result["market_confirmation_label"] = "No Market Data"
        return result

    snapshots = []
    for _, group in ohlcv_df.groupby("ticker"):
        snapshot = _technical_snapshot(group)
        if snapshot:
            snapshots.append(snapshot)

    if not snapshots:
        result["market_confirmation_score"] = float("nan")
        result["valuation_alignment_score"] = result["valuation_gap_pct"].apply(_alignment_score)
        result["market_confirmation_label"] = "No Market Data"
        return result

    technicals = pd.DataFrame(snapshots)
    merged = result.merge(technicals, on="ticker", how="left")
    merged["valuation_alignment_score"] = merged["valuation_gap_pct"].apply(_alignment_score)
    merged["market_confirmation_label"] = merged.apply(_confirmation_label, axis=1)
    return merged


def calculate_market_betas(
    ohlcv_df: pd.DataFrame,
    lookback_sessions: int = 252,
    min_observations: int = 120,
    min_beta: float = 0.30,
    max_beta: float = 2.50,
) -> pd.DataFrame:
    """
    Estimate each ticker's beta against an equal-weight bank-universe benchmark.
    The benchmark excludes the ticker being estimated to avoid self-correlation.
    """
    if ohlcv_df.empty or "ticker" not in ohlcv_df.columns or "close" not in ohlcv_df.columns:
        return pd.DataFrame(columns=["ticker", "beta", "beta_observations", "beta_benchmark"])

    prices = ohlcv_df.copy()
    prices["time"] = pd.to_datetime(prices["time"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["time", "ticker", "close"])
    if prices.empty:
        return pd.DataFrame(columns=["ticker", "beta", "beta_observations", "beta_benchmark"])

    close = prices.pivot_table(index="time", columns="ticker", values="close", aggfunc="last").sort_index()
    returns = close.ffill().pct_change().replace([float("inf"), -float("inf")], pd.NA)
    returns = returns.tail(lookback_sessions).dropna(how="all")

    rows = []
    for ticker in returns.columns:
        stock_returns = returns[ticker]
        peer_returns = returns.drop(columns=[ticker]).mean(axis=1, skipna=True)
        aligned = pd.concat([stock_returns, peer_returns], axis=1, keys=["stock", "benchmark"]).dropna()
        observations = len(aligned)
        if observations < min_observations:
            rows.append({
                "ticker": ticker,
                "beta": float("nan"),
                "beta_observations": observations,
                "beta_benchmark": "BANK_EW_EX_SELF",
            })
            continue

        benchmark_var = aligned["benchmark"].var()
        if pd.isna(benchmark_var) or benchmark_var == 0:
            beta = float("nan")
        else:
            beta = aligned["stock"].cov(aligned["benchmark"]) / benchmark_var
            if pd.notna(beta):
                beta = max(min_beta, min(max_beta, float(beta)))

        rows.append({
            "ticker": ticker,
            "beta": beta,
            "beta_observations": observations,
            "beta_benchmark": "BANK_EW_EX_SELF",
        })

    return pd.DataFrame(rows)
