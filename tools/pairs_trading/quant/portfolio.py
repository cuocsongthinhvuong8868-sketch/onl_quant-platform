"""Capital-constrained aggregation of pair backtests."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PortfolioBacktestResult:
    equity: pd.DataFrame
    pair_weights: pd.Series
    ticker_exposures: pd.DataFrame
    latest_ticker_exposure: pd.Series
    stats: dict


def _portfolio_stats(curve: pd.DataFrame) -> dict:
    returns = curve["ret_net"]
    volatility = float(returns.std())
    return {
        "total_return": float(curve["equity"].iloc[-1] - 1.0),
        "sharpe": float(returns.mean() / volatility * np.sqrt(252)) if volatility > 0 else float("nan"),
        "max_dd": float(curve["drawdown"].min()),
        "annualized_volatility": volatility * np.sqrt(252),
        "gross_exposure_max": float(curve["gross_exposure"].max()),
        "net_exposure_max_abs": float(curve["net_exposure"].abs().max()),
        "turnover": float(curve["turnover"].sum()),
        "cost_drag": float(curve["cost"].sum()),
    }


def aggregate_pair_backtests(
    backtests: dict[str, pd.DataFrame],
    *,
    max_pair_weight: float = 0.25,
    tc_bps_one_way: float = 0.0,
    sell_tax_bps: float = 0.0,
    borrow_bps_annual: float = 0.0,
) -> PortfolioBacktestResult:
    """Aggregate pair books, then charge costs on the netted ticker book.

    Pair allocations are fixed ex ante. Gross returns are additive under those
    allocations; execution, sell-tax and borrow costs are recomputed from the
    aggregate ticker exposure so opposite uses of a shared leg offset before
    turnover and financing are charged.
    """
    valid = {
        name: frame.sort_index()
        for name, frame in backtests.items()
        if not frame.empty
        and {"weight_1", "weight_2"}.issubset(frame.columns)
        and ("ret_gross" in frame or "ret_net" in frame)
    }
    if not valid:
        raise ValueError("Không có pair backtest hợp lệ để aggregate")
    if not 0 < max_pair_weight <= 1:
        raise ValueError("max_pair_weight phải thuộc (0, 1]")
    if tc_bps_one_way < 0 or sell_tax_bps < 0 or borrow_bps_annual < 0:
        raise ValueError("Portfolio cost bps phải >= 0")
    names = sorted(valid)
    allocation = min(1.0 / len(names), float(max_pair_weight))
    weights = pd.Series(allocation, index=names, name="portfolio_weight")
    all_dates = pd.Index(sorted(set().union(*(frame.index for frame in valid.values()))))
    pair_gross_returns = pd.DataFrame(
        {
            name: (
                frame["ret_gross"] if "ret_gross" in frame else frame["ret_net"]
            ).reindex(all_dates).fillna(0.0)
            for name, frame in valid.items()
        }
    )
    portfolio_gross_return = pair_gross_returns.mul(weights, axis=1).sum(axis=1)

    exposure_columns: dict[str, pd.Series] = {}
    for name, frame in valid.items():
        try:
            t1, t2 = name.split("/", 1)
        except ValueError as exc:
            raise ValueError(f"Pair name phải có dạng T1/T2: {name}") from exc
        w1 = frame["weight_1"].reindex(all_dates).fillna(0.0) * weights[name]
        w2 = frame["weight_2"].reindex(all_dates).fillna(0.0) * weights[name]
        exposure_columns[t1] = exposure_columns.get(t1, pd.Series(0.0, index=all_dates)).add(w1, fill_value=0)
        exposure_columns[t2] = exposure_columns.get(t2, pd.Series(0.0, index=all_dates)).add(w2, fill_value=0)
    exposures = pd.DataFrame(exposure_columns, index=all_dates).fillna(0.0)
    gross_exposure = exposures.abs().sum(axis=1)
    net_exposure = exposures.sum(axis=1)
    prior_exposures = exposures.shift(1).fillna(0.0)
    exposure_changes = exposures - prior_exposures
    turnover = exposure_changes.abs().sum(axis=1)
    sell_turnover = (-exposure_changes).clip(lower=0.0).sum(axis=1)
    short_exposure = (-prior_exposures).clip(lower=0.0).sum(axis=1)
    execution_cost = turnover * float(tc_bps_one_way) / 1e4
    sell_tax = sell_turnover * float(sell_tax_bps) / 1e4
    borrow_cost = short_exposure * float(borrow_bps_annual) / 1e4 / 252.0
    cost = execution_cost + sell_tax + borrow_cost
    portfolio_return = portfolio_gross_return - cost
    equity = (1.0 + portfolio_return).cumprod()
    curve = pd.DataFrame(
        {
            "ret_gross": portfolio_gross_return,
            "execution_cost": execution_cost,
            "sell_tax": sell_tax,
            "borrow_cost": borrow_cost,
            "cost": cost,
            "turnover": turnover,
            "ret_net": portfolio_return,
            "equity": equity,
            "drawdown": equity / equity.cummax() - 1.0,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
        },
        index=all_dates,
    )
    nonzero = exposures.loc[exposures.abs().sum(axis=1) > 0]
    latest = (
        nonzero.iloc[-1].sort_values(key=lambda values: values.abs(), ascending=False)
        if not nonzero.empty
        else pd.Series(dtype=float)
    )
    return PortfolioBacktestResult(
        equity=curve,
        pair_weights=weights,
        ticker_exposures=exposures,
        latest_ticker_exposure=latest,
        stats=_portfolio_stats(curve),
    )
