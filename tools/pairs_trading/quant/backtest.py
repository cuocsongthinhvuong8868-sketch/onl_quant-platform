"""
backtest.py — Simple market-neutral basket PnL + transaction cost + order ticket.

Convention spread:
    spread_t = log(P1_t) - β·log(P2_t)
  position +1 (long spread)  = long P1, short β·P2
  position -1 (short spread) = short P1, long β·P2

P1 phase: no margin/lot/FOL — pure theoretical PnL with TC.
P2 phase: generate_order_ticket() adds VN-specific rounding + margin calc.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TC_BPS = 15.0           # 0.15% broker fee + ~0 sell tax (mua VN ko tax)
DEFAULT_MARGIN_RATE = 0.5       # VN retail thực tế ~50%
DEFAULT_LOT_SIZE = 100          # VN universal


def transaction_cost_model(turnover: pd.Series, bps_round_trip: float = DEFAULT_TC_BPS) -> pd.Series:
    """Compute TC per period từ turnover (notional change). bps = basis points."""
    return turnover * (bps_round_trip / 1e4)


def basket_pnl(
    prices: pd.DataFrame,
    beta: float,
    signals: pd.DataFrame,
    t1: str,
    t2: str,
    tc_bps: float = DEFAULT_TC_BPS,
) -> pd.DataFrame:
    """Compute equity curve cho 1 pair.

    Parameters
    ----------
    prices : DF (cần columns [t1, t2])
    beta   : hedge ratio (từ EG step 1)
    signals: DF từ entry_exit_rules() — cols position, entry_date, exit_reason
    t1, t2 : ticker names
    tc_bps : round-trip transaction cost (basis points)

    Returns DF index=date, cols:
        position, ret_gross, ret_net, equity, drawdown, turnover
    """
    aligned = pd.concat(
        [prices[[t1, t2]], signals[["position"]]],
        axis=1, join="inner",
    ).dropna()
    if aligned.empty:
        return pd.DataFrame()

    p1 = aligned[t1].astype(float)
    p2 = aligned[t2].astype(float)
    pos = aligned["position"].astype(float)

    # Log return per leg
    ret1 = np.log(p1).diff().fillna(0.0)
    ret2 = np.log(p2).diff().fillna(0.0)

    # Spread return: +1 position → long P1, short β·P2
    # Use lagged position (signal known at t-1, applied at t)
    pos_lag = pos.shift(1).fillna(0.0)
    spread_ret = pos_lag * (ret1 - beta * ret2)

    # Turnover = |Δposition| × (1 + β) — assume rebalance both legs
    dpos = pos.diff().abs().fillna(0.0)
    turnover = dpos * (1.0 + abs(beta))
    tc = transaction_cost_model(turnover, tc_bps)

    ret_net = spread_ret - tc
    equity = (1.0 + ret_net).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0

    return pd.DataFrame(
        {
            "position": pos,
            "ret_gross": spread_ret,
            "ret_net": ret_net,
            "equity": equity,
            "drawdown": drawdown,
            "turnover": turnover,
        },
        index=aligned.index,
    )


def summary_stats(equity_curve: pd.DataFrame) -> dict:
    """Sharpe + max DD + hit-rate + total return từ equity curve."""
    if equity_curve.empty or "ret_net" not in equity_curve.columns:
        return {"sharpe": float("nan"), "max_dd": float("nan"),
                "hit_rate": float("nan"), "total_return": float("nan"),
                "n_trades": 0}
    ret = equity_curve["ret_net"]
    pos = equity_curve["position"]
    annualizer = np.sqrt(252)
    sharpe = (ret.mean() / ret.std() * annualizer) if ret.std() > 0 else float("nan")
    max_dd = equity_curve["drawdown"].min()
    in_trade = pos != 0
    hit_rate = (ret[in_trade] > 0).mean() if in_trade.any() else float("nan")
    total_return = equity_curve["equity"].iloc[-1] - 1.0
    # n_trades = số lần position thay đổi từ 0 → ±1
    trade_starts = ((pos.shift(1).fillna(0) == 0) & (pos != 0)).sum()
    return {
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "hit_rate": float(hit_rate),
        "total_return": float(total_return),
        "n_trades": int(trade_starts),
    }


def generate_order_ticket(
    t1: str,
    t2: str,
    side: int,                  # +1 = long spread (long t1, short t2), -1 = short spread
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
) -> dict:
    """Generate JSON-serializable order ticket cho 1 pair entry.

    P2 layer. VN-specific:
      - Quantity rounded to multiples of lot_size (100)
      - Margin = margin_rate × notional
      - Leg-2 notional / leg-1 notional ≈ |β| (từ EG step 1)
      - Tick rounding skip (broker auto-snap)

    Returns dict (JSON-safe).
    """
    if side not in (-1, +1):
        raise ValueError(f"side phải +1 hoặc -1, got {side}")
    if not np.isfinite(beta) or beta <= 0:
        raise ValueError(f"beta phải là số dương hữu hạn cho long/short ticket, got {beta}")
    if price1 <= 0 or price2 <= 0 or capital <= 0:
        raise ValueError("price1, price2 và capital phải > 0")
    if lot_size <= 0:
        raise ValueError("lot_size phải > 0")

    # Hedge-neutral sizing theo spread log(P1) - beta*log(P2):
    #   notional_leg2 ≈ beta * notional_leg1
    # và gross notional hai leg không vượt capital trước rounding.
    leg1_target_notional = capital / (1.0 + abs(beta))
    leg2_target_notional = capital - leg1_target_notional
    qty1 = int(np.floor(leg1_target_notional / price1 / lot_size) * lot_size)
    qty2 = int(np.floor(leg2_target_notional / price2 / lot_size) * lot_size)
    if qty1 <= 0 or qty2 <= 0:
        raise ValueError(f"Capital {capital} quá nhỏ cho lot size {lot_size} của {t1}/{t2}")

    if side == +1:
        leg1_side, leg2_side = "BUY", "SELL"
    else:
        leg1_side, leg2_side = "SELL", "BUY"

    leg1_notional = qty1 * price1
    leg2_notional = qty2 * price2
    gross_notional = leg1_notional + leg2_notional
    realized_beta = leg2_notional / leg1_notional
    hedge_error_pct = (realized_beta / abs(beta)) - 1.0
    margin_req = gross_notional * margin_rate
    margin_cushion = margin_req * 2.0  # spec §13.4 #1: capital cushion ≥ 2× initial margin

    ticket: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pair": [t1, t2],
        "legs": [
            {"ticker": t1, "side": leg1_side, "quantity": qty1, "limit_price": float(price1)},
            {"ticker": t2, "side": leg2_side, "quantity": qty2, "limit_price": float(price2)},
        ],
        "hedge_ratio_beta": float(beta),
        "realized_notional_hedge_ratio": float(realized_beta),
        "hedge_ratio_error_pct": float(hedge_error_pct),
        "leg1_notional_vnd": float(leg1_notional),
        "leg2_notional_vnd": float(leg2_notional),
        "z_at_entry": float(z_at_entry),
        "expected_half_life_days": float(half_life),
        "stop_z": float(stop_z),
        "notional_vnd": float(gross_notional),
        "margin_required_vnd": float(margin_req),
        "margin_cushion_2x_vnd": float(margin_cushion),
        "notes": (
            "Leg notionals are sized to the Engle-Granger beta subject to board-lot rounding. "
            "Assumes foreign_room > 5% (verify manually). "
            "Lunch break 11:30-13:00 ICT — orders may queue. "
            "Cointegration re-test mỗi 60 phiên — kiểm tra last refit trước khi vào lệnh."
        ),
    }
    if rho_at_entry is not None and np.isfinite(rho_at_entry):
        ticket["rho_at_entry"] = float(rho_at_entry)
        if rho_method is not None:
            ticket["rho_method"] = str(rho_method)
    return ticket


def order_ticket_to_json(ticket: dict) -> str:
    """Serialize order_ticket dict → JSON string (pretty print)."""
    return json.dumps(ticket, ensure_ascii=False, indent=2)
