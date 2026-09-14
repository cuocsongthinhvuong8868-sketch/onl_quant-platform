"""Canonical pair-analysis and point-in-time walk-forward engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tools.pairs_trading.quant.backtest import basket_pnl, summary_stats, trade_ledger
from tools.pairs_trading.quant.cointegration import (
    beta_stability,
    engle_granger,
    hurst,
    kalman_hedge_ratio,
    ou_half_life_diagnostics,
    rolling_hedge_ratio,
)
from tools.pairs_trading.quant.dcc_filter import pair_rho_result
from tools.pairs_trading.quant.signal import entry_exit_rules, z_score_60d


@dataclass(frozen=True)
class PairResearchConfig:
    formation_window: int = 252
    refit_every: int = 20
    z_window: int = 60
    z_method: str = "standard"
    entry_z: float = 2.0
    exit_band: float = 0.0
    stop_z: float = 3.0
    quarantine_sessions: int = 60
    alpha: float = 0.05
    hl_min: float = 5.0
    hl_max: float = 30.0
    min_rho: float = 0.5
    use_rho_filter: bool = False
    rho_method: str = "ewma"
    require_stability: bool = False
    hedge_method: str = "ols"
    tc_bps_one_way: float = 15.0
    sell_tax_bps: float = 10.0
    borrow_bps_annual: float = 0.0

    def __post_init__(self) -> None:
        if self.formation_window < 120:
            raise ValueError("formation_window phải >= 120")
        if self.refit_every < 1 or self.z_window < 20:
            raise ValueError("refit_every/z_window không hợp lệ")
        if not 0 <= self.exit_band < self.entry_z < self.stop_z:
            raise ValueError("Cần 0 <= exit_band < entry_z < stop_z")
        if self.hl_min <= 0 or self.hl_max <= self.hl_min:
            raise ValueError("Half-life range không hợp lệ")
        if self.z_method not in {"standard", "robust", "ewma"}:
            raise ValueError("z_method không hợp lệ")
        if self.hedge_method not in {"ols", "rolling", "kalman"}:
            raise ValueError("hedge_method không hợp lệ")
        if self.rho_method not in {"ewma", "dcc"}:
            raise ValueError("rho_method không hợp lệ")


@dataclass
class PairAnalysisResult:
    t1: str
    t2: str
    as_of: pd.Timestamp
    fit_start: pd.Timestamp
    n_obs: int
    beta: float
    alpha: float
    coint_stat: float
    p_value: float
    q_value: float
    i1_valid: bool
    cointegrated: bool
    half_life: float
    half_life_ci: tuple[float | None, float | None]
    hurst: float
    z_latest: float
    rho_now: float
    rho_method_requested: str
    rho_method_actual: str
    stability_score: float
    beta_drift: float | None
    eligible: bool
    eligibility_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    spread: pd.Series = field(repr=False)
    z_score: pd.Series = field(repr=False)
    rho_series: pd.Series = field(repr=False)
    methodology_version: str = "pairs_research_point_in_time_v2"

    @property
    def pair(self) -> str:
        return f"{self.t1}/{self.t2}"

    def to_record(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "t1": self.t1,
            "t2": self.t2,
            "as_of": self.as_of.strftime("%Y-%m-%d"),
            "fit_start": self.fit_start.strftime("%Y-%m-%d"),
            "n_obs": self.n_obs,
            "beta": self.beta,
            "coint_stat": self.coint_stat,
            "p_value": self.p_value,
            "q_value": self.q_value,
            "i1_valid": self.i1_valid,
            "cointegrated": self.cointegrated,
            "half_life": self.half_life,
            "half_life_ci_low": self.half_life_ci[0],
            "half_life_ci_high": self.half_life_ci[1],
            "hurst": self.hurst,
            "z_score": self.z_latest,
            "rho_now": self.rho_now,
            "rho_method_requested": self.rho_method_requested,
            "rho_method_actual": self.rho_method_actual,
            "stability_score": self.stability_score,
            "beta_drift": self.beta_drift,
            "eligible": self.eligible,
            "eligibility_reasons": list(self.eligibility_reasons),
            "warnings": list(self.warnings),
            "methodology_version": self.methodology_version,
        }


@dataclass
class WalkForwardResult:
    t1: str
    t2: str
    signals: pd.DataFrame
    equity: pd.DataFrame
    ledger: pd.DataFrame
    stats: dict[str, Any]
    refits: pd.DataFrame
    methodology_version: str = "pairs_walk_forward_v2"


def _clean_pair(prices: pd.DataFrame, t1: str, t2: str) -> pd.DataFrame:
    if t1 == t2 or t1 not in prices or t2 not in prices:
        raise ValueError(f"Pair không hợp lệ: {t1}/{t2}")
    pair = prices[[t1, t2]].apply(pd.to_numeric, errors="coerce")
    pair = pair.replace([np.inf, -np.inf], np.nan).where(lambda frame: frame > 0)
    pair = pair.dropna(how="any").loc[lambda frame: ~frame.index.duplicated(keep="last")].sort_index()
    if len(pair) < 120:
        raise ValueError(f"{t1}/{t2}: cần >=120 common observations, có {len(pair)}")
    return pair


def _eligibility_reasons(
    eg: dict,
    half_life: float,
    stability: dict,
    rho_now: float,
    config: PairResearchConfig,
    q_value: float,
) -> list[str]:
    reasons: list[str] = []
    if not eg.get("i1_valid", False):
        reasons.append("legs_not_i1")
    if not np.isfinite(q_value) or q_value >= config.alpha:
        reasons.append("cointegration_q_failed")
    if not np.isfinite(eg.get("beta", np.nan)) or eg["beta"] <= 0:
        reasons.append("nonpositive_beta")
    if not np.isfinite(half_life) or not config.hl_min <= half_life <= config.hl_max:
        reasons.append("half_life_outside_band")
    if config.require_stability and not stability.get("stable", False):
        reasons.append("beta_unstable")
    if config.use_rho_filter and (not np.isfinite(rho_now) or rho_now < config.min_rho):
        reasons.append("rho_below_threshold")
    return reasons


def analyze_pair(
    prices: pd.DataFrame,
    t1: str,
    t2: str,
    config: PairResearchConfig | None = None,
    *,
    q_value: float | None = None,
) -> PairAnalysisResult:
    """One canonical current-as-of analysis consumed by UI, scanner and report."""
    cfg = config or PairResearchConfig()
    pair = _clean_pair(prices, t1, t2).tail(cfg.formation_window)
    eg = engle_granger(pair[t1], pair[t2], alpha=cfg.alpha)
    half = ou_half_life_diagnostics(eg["resid"])
    half_life = float(half["half_life"])
    stability = beta_stability(pair, t1, t2, window=min(126, max(60, len(pair) // 2)))
    z = z_score_60d(eg["resid"], cfg.z_window, method=cfg.z_method, lagged=True)
    z_clean = z.dropna()
    rho = pair_rho_result(pair, t1, t2, method=cfg.rho_method)
    resolved_q = float(eg["p_value"] if q_value is None else q_value)
    reasons = _eligibility_reasons(
        eg, half_life, stability, float(rho["rho_now"]), cfg, resolved_q
    )
    warnings: list[str] = []
    if not stability.get("stable", False):
        warnings.append("Beta drift/CV exceeds 25%.")
    if rho.get("warning"):
        warnings.append(str(rho["warning"]))
    return PairAnalysisResult(
        t1=t1,
        t2=t2,
        as_of=pd.Timestamp(pair.index[-1]),
        fit_start=pd.Timestamp(pair.index[0]),
        n_obs=int(len(pair)),
        beta=float(eg["beta"]),
        alpha=float(eg["alpha"]),
        coint_stat=float(eg["coint_stat"]),
        p_value=float(eg["p_value"]),
        q_value=resolved_q,
        i1_valid=bool(eg["i1_valid"]),
        cointegrated=bool(eg["is_cointegrated"]),
        half_life=half_life,
        half_life_ci=(half["ci_low"], half["ci_high"]),
        hurst=float(hurst(eg["resid"])),
        z_latest=float(z_clean.iloc[-1]) if not z_clean.empty else float("nan"),
        rho_now=float(rho["rho_now"]),
        rho_method_requested=str(rho["requested_method"]),
        rho_method_actual=str(rho["actual_method"]),
        stability_score=float(stability["score"]),
        beta_drift=stability["drift"],
        eligible=not reasons,
        eligibility_reasons=tuple(reasons),
        warnings=tuple(warnings),
        spread=eg["resid"],
        z_score=z,
        rho_series=rho["series"],
    )


def _causal_hedge_beta(
    pair: pd.DataFrame,
    t1: str,
    t2: str,
    method: str,
    fallback: pd.Series,
) -> pd.Series:
    fallback = pd.to_numeric(fallback.reindex(pair.index), errors="coerce")
    if method == "rolling":
        dynamic = rolling_hedge_ratio(pair[t1], pair[t2], window=126)
        dynamic = dynamic.reindex(pair.index).where(lambda values: np.isfinite(values) & (values > 0))
        return dynamic.combine_first(fallback)
    if method == "kalman":
        dynamic = kalman_hedge_ratio(pair[t1], pair[t2])
        dynamic = dynamic.reindex(pair.index).where(lambda values: np.isfinite(values) & (values > 0))
        return dynamic.combine_first(fallback)
    return fallback


def walk_forward_backtest(
    prices: pd.DataFrame,
    t1: str,
    t2: str,
    config: PairResearchConfig | None = None,
) -> WalkForwardResult:
    """Causal formation/trading backtest with periodic model refits."""
    cfg = config or PairResearchConfig()
    pair = _clean_pair(prices, t1, t2)
    if len(pair) <= cfg.formation_window + 20:
        raise ValueError(
            f"Walk-forward cần > formation_window+20 obs, có {len(pair)}"
        )
    index = pair.index
    z_values = pd.Series(np.nan, index=index, name="z_score")
    beta_values = pd.Series(np.nan, index=index, name="beta")
    half_lives = pd.Series(np.nan, index=index, name="half_life")
    eligible = pd.Series(False, index=index, name="eligible")
    p_values = pd.Series(np.nan, index=index, name="p_value")
    refit_rows: list[dict[str, Any]] = []

    # A single full-sample DCC fit would leak fitted parameters into early
    # history. Use causal EWMA for historical gating; DCC remains available for
    # current-as-of diagnostics in analyze_pair().
    rho = pair_rho_result(pair, t1, t2, method="ewma")
    rho_series = rho["series"].reindex(index)
    for start in range(cfg.formation_window, len(pair), cfg.refit_every):
        end = min(start + cfg.refit_every, len(pair))
        training = pair.iloc[start - cfg.formation_window:start]
        trade_dates = index[start:end]
        try:
            eg = engle_granger(training[t1], training[t2], alpha=cfg.alpha)
            half = ou_half_life_diagnostics(eg["resid"])
            half_life = float(half["half_life"])
            stability = beta_stability(
                training, t1, t2, window=min(126, max(60, len(training) // 2))
            )
            q_value = float(eg["p_value"])
            train_reasons = _eligibility_reasons(
                eg, half_life, stability, float("nan"), cfg, q_value
            )
            # Rho is a per-date gate below; do not let a missing final rho poison the block.
            train_reasons = [reason for reason in train_reasons if reason != "rho_below_threshold"]
            history = pair.iloc[max(0, start - cfg.formation_window):end]
            spread = (
                np.log(history[t1])
                - float(eg["alpha"])
                - float(eg["beta"]) * np.log(history[t2])
            )
            block_z = z_score_60d(
                spread, cfg.z_window, method=cfg.z_method, lagged=True
            ).reindex(trade_dates)
            z_values.loc[trade_dates] = block_z
            beta_values.loc[trade_dates] = float(eg["beta"])
            half_lives.loc[trade_dates] = half_life
            p_values.loc[trade_dates] = float(eg["p_value"])
            block_eligible = pd.Series(not train_reasons, index=trade_dates)
            if cfg.use_rho_filter:
                block_rho = rho_series.reindex(trade_dates)
                block_eligible &= block_rho.notna() & (block_rho >= cfg.min_rho)
            eligible.loc[trade_dates] = block_eligible
            refit_rows.append(
                {
                    "model_as_of": training.index[-1],
                    "trade_start": trade_dates[0],
                    "trade_end": trade_dates[-1],
                    "beta": float(eg["beta"]),
                    "p_value": float(eg["p_value"]),
                    "i1_valid": bool(eg["i1_valid"]),
                    "half_life": half_life,
                    "stability_score": float(stability["score"]),
                    "eligible": not train_reasons,
                    "reasons": ",".join(train_reasons),
                }
            )
        except Exception as exc:
            refit_rows.append(
                {
                    "model_as_of": training.index[-1],
                    "trade_start": trade_dates[0],
                    "trade_end": trade_dates[-1],
                    "eligible": False,
                    "reasons": f"fit_error:{type(exc).__name__}",
                }
            )

    signal_input = z_values.dropna()
    signal_frame = entry_exit_rules(
        signal_input,
        entry=cfg.entry_z,
        exit_band=cfg.exit_band,
        stop=cfg.stop_z,
        half_life=half_lives,
        eligible=eligible,
        quarantine_bars=cfg.quarantine_sessions,
        exit_on_ineligible=True,
    )
    signal_frame["z_score"] = signal_input
    signal_frame["beta"] = beta_values.reindex(signal_frame.index)
    signal_frame["half_life"] = half_lives.reindex(signal_frame.index)
    signal_frame["p_value"] = p_values.reindex(signal_frame.index)
    signal_frame["rho"] = rho_series.reindex(signal_frame.index)
    hedge_beta = _causal_hedge_beta(
        pair,
        t1,
        t2,
        cfg.hedge_method,
        beta_values,
    ).reindex(signal_frame.index)
    equity = basket_pnl(
        pair,
        hedge_beta,
        signal_frame,
        t1,
        t2,
        tc_bps=cfg.tc_bps_one_way,
        sell_tax_bps=cfg.sell_tax_bps,
        borrow_bps_annual=cfg.borrow_bps_annual,
        liquidate_at_end=True,
    )
    ledger = trade_ledger(equity)
    return WalkForwardResult(
        t1=t1,
        t2=t2,
        signals=signal_frame,
        equity=equity,
        ledger=ledger,
        stats=summary_stats(equity),
        refits=pd.DataFrame(refit_rows),
    )
