"""Gross-normalized pairs PnL, trade ledger, and strict order tickets."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ``tc_bps`` is now explicitly a one-way broker/slippage cost per traded notional.
DEFAULT_TC_BPS = 15.0
DEFAULT_SELL_TAX_BPS = 10.0
DEFAULT_BORROW_BPS_ANNUAL = 0.0
DEFAULT_MARGIN_RATE = 0.5
DEFAULT_LOT_SIZE = 100
VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def transaction_cost_model(turnover: pd.Series, bps_one_way: float = DEFAULT_TC_BPS) -> pd.Series:
    """One-way execution cost as a fraction of gross capital."""
    if bps_one_way < 0:
        raise ValueError("bps_one_way phải >= 0")
    return turnover.astype(float) * (float(bps_one_way) / 1e4)


def _beta_series(beta: float | pd.Series, index: pd.Index) -> pd.Series:
    if isinstance(beta, pd.Series):
        values = pd.to_numeric(beta.reindex(index), errors="coerce").ffill()
    else:
        values = pd.Series(float(beta), index=index, dtype=float)
    return values.where(np.isfinite(values) & (values > 0))


def basket_pnl(
    prices: pd.DataFrame,
    beta: float | pd.Series,
    signals: pd.DataFrame,
    t1: str,
    t2: str,
    tc_bps: float = DEFAULT_TC_BPS,
    *,
    sell_tax_bps: float = DEFAULT_SELL_TAX_BPS,
    borrow_bps_annual: float = DEFAULT_BORROW_BPS_ANNUAL,
    liquidate_at_end: bool = True,
) -> pd.DataFrame:
    """Backtest gross-normalized target weights with point-in-time beta.

    A signal observed at close t becomes the target held over t→t+1. Costs are
    charged whenever target weights change. The final target is flattened by
    default so every reported trade includes its closing cost.
    """
    if t1 == t2 or t1 not in prices or t2 not in prices:
        raise ValueError("Cần hai ticker khác nhau có trong prices")
    if tc_bps < 0 or sell_tax_bps < 0 or borrow_bps_annual < 0:
        raise ValueError("Các cost bps phải >= 0")
    aligned = pd.concat(
        [prices[[t1, t2]].apply(pd.to_numeric, errors="coerce"), signals[["position"]]],
        axis=1,
        join="inner",
    ).replace([np.inf, -np.inf], np.nan).dropna()
    aligned = aligned[(aligned[t1] > 0) & (aligned[t2] > 0)].sort_index()
    if aligned.empty:
        return pd.DataFrame()

    position = aligned["position"].astype(float).clip(-1, 1)
    beta_values = _beta_series(beta, aligned.index)
    position = position.where(beta_values.notna(), 0.0)
    if liquidate_at_end and len(position):
        position.iloc[-1] = 0.0

    denom = 1.0 + beta_values.abs()
    target_w1 = (position / denom).fillna(0.0)
    target_w2 = (-position * beta_values / denom).fillna(0.0)
    prior_w1 = target_w1.shift(1).fillna(0.0)
    prior_w2 = target_w2.shift(1).fillna(0.0)

    ret1 = aligned[t1].pct_change().fillna(0.0)
    ret2 = aligned[t2].pct_change().fillna(0.0)
    ret_gross = prior_w1 * ret1 + prior_w2 * ret2

    delta_w1 = target_w1 - prior_w1
    delta_w2 = target_w2 - prior_w2
    turnover = delta_w1.abs() + delta_w2.abs()
    sell_turnover = (-delta_w1).clip(lower=0) + (-delta_w2).clip(lower=0)
    execution_cost = transaction_cost_model(turnover, tc_bps)
    sell_tax = sell_turnover * (float(sell_tax_bps) / 1e4)
    short_exposure = (-prior_w1).clip(lower=0) + (-prior_w2).clip(lower=0)
    borrow_cost = short_exposure * (float(borrow_bps_annual) / 1e4 / 252.0)
    total_cost = execution_cost + sell_tax + borrow_cost
    ret_net = ret_gross - total_cost
    equity = (1.0 + ret_net).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return pd.DataFrame(
        {
            "position": position.astype(int),
            "beta": beta_values,
            "weight_1": target_w1,
            "weight_2": target_w2,
            "gross_exposure": target_w1.abs() + target_w2.abs(),
            "net_exposure": target_w1 + target_w2,
            "ret_gross": ret_gross,
            "execution_cost": execution_cost,
            "sell_tax": sell_tax,
            "borrow_cost": borrow_cost,
            "cost": total_cost,
            "ret_net": ret_net,
            "equity": equity,
            "drawdown": drawdown,
            "turnover": turnover,
        },
        index=aligned.index,
    )


def trade_ledger(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Build one row per completed position episode."""
    if equity_curve.empty:
        return pd.DataFrame()
    position = equity_curve["position"].astype(int)
    rows: list[dict] = []
    entry_i: int | None = None
    side = 0
    for i, current in enumerate(position.to_numpy()):
        previous = int(position.iloc[i - 1]) if i > 0 else 0
        if previous == 0 and current != 0:
            entry_i, side = i, int(current)
        if entry_i is not None and previous != 0 and current == 0:
            window = equity_curve.iloc[entry_i:i + 1]
            gross = float((1.0 + window["ret_gross"]).prod() - 1.0)
            net = float((1.0 + window["ret_net"]).prod() - 1.0)
            rows.append(
                {
                    "entry_date": equity_curve.index[entry_i],
                    "exit_date": equity_curve.index[i],
                    "side": side,
                    "holding_sessions": int(i - entry_i),
                    "gross_return": gross,
                    "net_return": net,
                    "cost_drag": gross - net,
                }
            )
            entry_i, side = None, 0
    return pd.DataFrame(rows)


def summary_stats(equity_curve: pd.DataFrame) -> dict:
    """Portfolio and completed-trade statistics."""
    empty = {
        "sharpe": float("nan"), "max_dd": float("nan"),
        "hit_rate": float("nan"), "win_rate": float("nan"),
        "positive_day_rate": float("nan"), "total_return": float("nan"),
        "n_trades": 0, "avg_holding_sessions": float("nan"), "cost_drag": 0.0,
    }
    if equity_curve.empty or "ret_net" not in equity_curve:
        return empty
    returns = equity_curve["ret_net"].astype(float)
    volatility = returns.std()
    sharpe = returns.mean() / volatility * np.sqrt(252) if volatility > 0 else float("nan")
    ledger = trade_ledger(equity_curve)
    win_rate = float((ledger["net_return"] > 0).mean()) if not ledger.empty else float("nan")
    in_trade = equity_curve["gross_exposure"] > 0 if "gross_exposure" in equity_curve else equity_curve["position"] != 0
    positive_day_rate = float((returns[in_trade] > 0).mean()) if in_trade.any() else float("nan")
    total_return = float(equity_curve["equity"].iloc[-1] - 1.0)
    return {
        "sharpe": float(sharpe),
        "max_dd": float(equity_curve["drawdown"].min()),
        "hit_rate": win_rate,
        "win_rate": win_rate,
        "positive_day_rate": positive_day_rate,
        "total_return": total_return,
        "n_trades": int(len(ledger)),
        "avg_holding_sessions": float(ledger["holding_sessions"].mean()) if not ledger.empty else float("nan"),
        "cost_drag": float(equity_curve.get("cost", pd.Series(0.0, index=equity_curve.index)).sum()),
    }


def generate_order_ticket(
    t1: str,
    t2: str,
    side: int,
    beta: float,
    price1: float,
    price2: float,
    capital: float,
    z_at_entry: float,
    half_life: float,
    margin_rate: float = DEFAULT_MARGIN_RATE,
    lot_size: int = DEFAULT_LOT_SIZE,
    stop_z: float = 3.0,
    rho_at_entry: Optional[float] = None,
    rho_method: Optional[str] = None,
    *,
    data_as_of: str | None = None,
    model_as_of: str | None = None,
    adjusted_verified: bool = False,
    borrow_confirmed: bool = False,
    foreign_room_verified: bool = False,
    shortable: bool = False,
    execution_checks: dict[str, bool] | None = None,
    require_execution_checks: bool = False,
) -> dict:
    """Generate a versioned, JSON-strict, auditable research order ticket."""
    numeric = [beta, price1, price2, capital, z_at_entry, half_life, margin_rate, stop_z]
    if side not in (-1, 1):
        raise ValueError(f"side phải +1 hoặc -1, got {side}")
    if not all(np.isfinite(value) for value in numeric):
        raise ValueError("Ticket inputs phải là số hữu hạn")
    if beta <= 0 or price1 <= 0 or price2 <= 0 or capital <= 0:
        raise ValueError("beta, price1, price2 và capital phải > 0")
    if lot_size <= 0 or not 0 < margin_rate <= 1:
        raise ValueError("lot_size/margin_rate không hợp lệ")
    checks = {
        "adjusted_price_verified": bool(adjusted_verified),
        "borrow_confirmed": bool(borrow_confirmed),
        "foreign_room_verified": bool(foreign_room_verified),
        "short_leg_is_shortable": bool(shortable),
    }
    if execution_checks:
        checks.update({str(name): bool(passed) for name, passed in execution_checks.items()})
    if require_execution_checks:
        required_checks = {
            "adjusted_price_verified",
            "borrow_confirmed",
            "foreign_room_verified",
            "short_leg_is_shortable",
            "fresh_data",
            "common_quote",
            "liquidity_ok",
            "model_current",
        }
        failed = sorted(name for name in required_checks if not checks.get(name, False))
        if failed:
            raise ValueError("Execution gate chưa pass: " + ", ".join(failed))
        if not data_as_of or not model_as_of:
            raise ValueError("Execution gate cần data_as_of và model_as_of")

    leg1_target = capital / (1.0 + abs(beta))
    leg2_target = capital - leg1_target
    qty1 = int(np.floor(leg1_target / price1 / lot_size) * lot_size)
    qty2 = int(np.floor(leg2_target / price2 / lot_size) * lot_size)
    if qty1 <= 0 or qty2 <= 0:
        raise ValueError(f"Capital {capital} quá nhỏ cho lot size {lot_size} của {t1}/{t2}")
    leg1_side, leg2_side = (("BUY", "SELL") if side == 1 else ("SELL", "BUY"))
    leg1_notional, leg2_notional = qty1 * price1, qty2 * price2
    gross_notional = leg1_notional + leg2_notional
    realized_beta = leg2_notional / leg1_notional
    now = datetime.now(VIETNAM_TIMEZONE)
    ticket = {
        "schema_version": "pair_order_ticket_v2",
        "ticket_id": str(uuid.uuid4()),
        "timestamp": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(minutes=15)).isoformat(timespec="seconds"),
        "currency": "VND",
        "research_only": True,
        "data_as_of": data_as_of,
        "model_as_of": model_as_of,
        "pair": [str(t1), str(t2)],
        "legs": [
            {"ticker": str(t1), "side": leg1_side, "quantity": qty1, "reference_price": float(price1)},
            {"ticker": str(t2), "side": leg2_side, "quantity": qty2, "reference_price": float(price2)},
        ],
        "hedge_ratio_beta": float(beta),
        "realized_notional_hedge_ratio": float(realized_beta),
        "hedge_ratio_error_pct": float(realized_beta / abs(beta) - 1.0),
        "leg1_notional_vnd": float(leg1_notional),
        "leg2_notional_vnd": float(leg2_notional),
        "z_at_entry": float(z_at_entry),
        "expected_half_life_sessions": float(half_life),
        # Backward-compatible field name.
        "expected_half_life_days": float(half_life),
        "stop_z": float(stop_z),
        "notional_vnd": float(gross_notional),
        "margin_required_vnd": float(gross_notional * margin_rate),
        "margin_cushion_2x_vnd": float(gross_notional * margin_rate * 2.0),
        "execution_checks": checks,
        "notes": "Research ticket only; broker borrow, exchange price band and executable quote must be revalidated.",
    }
    if rho_at_entry is not None and np.isfinite(rho_at_entry):
        ticket["rho_at_entry"] = float(rho_at_entry)
        if rho_method:
            ticket["rho_method"] = str(rho_method)
    return ticket


def order_ticket_to_json(ticket: dict) -> str:
    return json.dumps(ticket, ensure_ascii=False, indent=2, allow_nan=False)
