"""Point-in-time state machine for market capitulation.

The module deliberately separates three concepts:

* structural fragility (weak trend, breadth and liquidity),
* acute liquidation pressure (price/breadth/forced-selling shocks), and
* exhaustion evidence after a liquidation climax.

Scores are deterministic, uncalibrated diagnostics on a 0-100 scale.  They are
not event probabilities.  Every rolling percentile compares an observation
only with observations strictly before it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

import numpy as np
import pandas as pd


METHODOLOGY_VERSION = "capitulation_state_machine_v1.0.0"


class CapitulationPhase(str, Enum):
    """Ordered market states emitted by the diagnostic engine."""

    NORMAL = "NORMAL"
    FRAGILE = "FRAGILE"
    LIQUIDATION = "LIQUIDATION"
    CAPITULATION_CLIMAX = "CAPITULATION_CLIMAX"
    EXHAUSTION_CONFIRMED = "EXHAUSTION_CONFIRMED"
    REPAIR = "REPAIR"


@dataclass(frozen=True)
class CapitulationConfig:
    """Transparent thresholds for the deterministic state machine."""

    ma_windows: tuple[int, ...] = (20, 60, 125, 252)
    index_ma_window: int = 200
    new_low_window: int = 252
    short_new_low_window: int = 60
    percentile_lookback: int | None = 756
    percentile_min_history: int = 120
    external_metric_max_session_lag: int = 1
    max_price_ffill: int = 3
    min_constituents: int = 5
    min_breadth_coverage: float = 0.70
    fragile_drawdown: float = -0.07
    fragile_breadth: float = 0.30
    fragile_turnover_ratio: float = 0.75
    price_shock_1d: float = -0.035
    price_shock_5d: float = -0.08
    liquidation_return_1d: float = -0.025
    liquidation_return_5d: float = -0.06
    shock_percentile: float = 0.95
    breadth_shock_percentile: float = 0.90
    downside_participation_shock: float = 0.80
    severe_downside_cutoff: float = -0.03
    severe_downside_share: float = 0.15
    new_low_share: float = 0.25
    climax_breadth_ma20: float = 0.15
    selling_volume_ratio: float = 1.50
    esr_stress: float = 0.60
    esr_liquidation: float = 0.80
    abm_vulnerability: float = 0.60
    abm_forced_vulnerability: float = 0.75
    abm_margin_distance: float = 0.05
    abm_forced_share: float = 0.25
    abm_liquidation_share: float = 0.60
    exhaustion_lookback: int = 5
    exhaustion_min_bounce: float = 0.012
    repair_lookback: int = 60


@dataclass(frozen=True)
class DataQuality:
    """Coverage and limitations attached to a snapshot."""

    status: str
    index_observations: int
    constituent_count: int
    current_breadth_coverage: float
    current_volume_coverage: float | None
    volume_source: str | None
    percentile_method: str
    available_features: tuple[str, ...]
    missing_features: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitulationSnapshot:
    """Typed output for one as-of date.

    The three ``*_uncalibrated`` fields are evidence scores, not probabilities.
    ``action_eligible`` is fail-closed: it is true only for confirmed exhaustion
    with non-insufficient data quality, never for an active selling climax.
    """

    as_of: pd.Timestamp
    phase: CapitulationPhase
    stress_risk_score_uncalibrated: float
    liquidation_risk_score_uncalibrated: float
    exhaustion_evidence_score_uncalibrated: float
    features: dict[str, float | str | None]
    percentiles: dict[str, float | None]
    required_gates_met: dict[str, bool]
    trigger_reasons: tuple[str, ...]
    confirmation_reasons: tuple[str, ...]
    data_quality: DataQuality
    action_eligible: bool
    methodology_version: str = METHODOLOGY_VERSION
    score_interpretation: str = (
        "Deterministic 0-100 evidence scores; uncalibrated and not probabilities."
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["phase"] = self.phase.value
        return payload

    as_dict = to_dict


def _clip01(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(np.clip(value, 0.0, 1.0))


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _fraction(value: Any) -> float | None:
    """Normalize a share supplied either as [0, 1] or percentage points."""

    number = _finite_float(value)
    if number is None or number < 0:
        return None
    if number > 1.0:
        number /= 100.0
    return _clip01(number)


def _weighted_score(parts: list[tuple[float | None, float]]) -> float:
    valid = [(value, weight) for value, weight in parts if value is not None]
    if not valid:
        return 0.0
    numerator = sum(float(value) * weight for value, weight in valid)
    denominator = sum(weight for _, weight in valid)
    return round(100.0 * numerator / denominator, 1)


def _as_datetime_index(obj: pd.Series | pd.DataFrame, name: str) -> pd.Series | pd.DataFrame:
    out = obj.copy()
    try:
        out.index = pd.DatetimeIndex(pd.to_datetime(out.index))
    except Exception as exc:  # pragma: no cover - pandas error text varies
        raise TypeError(f"{name} must have a datetime-like index") from exc
    out = out.loc[~out.index.duplicated(keep="last")].sort_index()
    return out


def _align_as_of(index: pd.DatetimeIndex, as_of: Any | None) -> pd.Timestamp:
    if index.empty:
        raise ValueError("index_close contains no observations")
    stamp = index[-1] if as_of is None else pd.Timestamp(as_of)
    if index.tz is None and stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    elif index.tz is not None and stamp.tzinfo is None:
        stamp = stamp.tz_localize(index.tz)
    elif index.tz is not None and stamp.tzinfo is not None:
        stamp = stamp.tz_convert(index.tz)
    return stamp


def _prepare_series(data: pd.Series, name: str) -> pd.Series:
    if not isinstance(data, pd.Series):
        raise TypeError(f"{name} must be a pandas Series")
    out = _as_datetime_index(data, name)
    out = pd.to_numeric(out, errors="coerce").astype(float)
    out.name = name
    return out


def _prepare_frame(data: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    out = _as_datetime_index(data, name)
    out = out.loc[:, ~out.columns.duplicated(keep="last")]
    return out.apply(pd.to_numeric, errors="coerce").astype(float)


def _prior_percentile(
    series: pd.Series,
    *,
    higher_is_stress: bool,
    lookback: int | None,
    min_history: int,
) -> pd.Series:
    """Rank each value against strictly prior observations.

    Mid-ranks make flat histories deterministic.  The explicit loop is easier to
    audit than a rolling callback that can accidentally include the live row.
    """

    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    for position, current in enumerate(values):
        if not np.isfinite(current):
            continue
        start = 0 if lookback is None else max(0, position - lookback)
        history = values[start:position]
        history = history[np.isfinite(history)]
        if history.size < min_history:
            continue
        lower = np.count_nonzero(history < current)
        equal = np.count_nonzero(history == current)
        percentile = (lower + 0.5 * equal) / history.size
        result[position] = percentile if higher_is_stress else 1.0 - percentile
    return pd.Series(result, index=series.index, name=f"{series.name}_stress_percentile")


def _normalize_mapping(data: Any, as_of: pd.Timestamp) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, pd.DataFrame):
        frame = _as_datetime_index(data, "external metrics")
        prior = frame.loc[frame.index <= as_of]
        return {} if prior.empty else prior.iloc[-1].to_dict()
    if isinstance(data, pd.Series):
        if isinstance(data.index, pd.DatetimeIndex):
            prior = data.loc[data.index <= as_of]
            return {} if prior.empty else {str(data.name or "value"): prior.iloc[-1]}
        return data.to_dict()
    if hasattr(data, "__dataclass_fields__"):
        data = asdict(data)
    if not isinstance(data, Mapping):
        raise TypeError("ESR/ABM metrics must be a mapping, Series, DataFrame or dataclass")

    output: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, pd.Series) and isinstance(value.index, pd.DatetimeIndex):
            prior = value.loc[value.index <= as_of]
            output[str(key)] = None if prior.empty else prior.iloc[-1]
        else:
            output[str(key)] = value
    return output


def _lookup(data: Mapping[str, Any], *names: str) -> Any:
    normalized = {str(key).lower().replace(" ", "_"): value for key, value in data.items()}
    for name in names:
        key = name.lower().replace(" ", "_")
        if key in normalized:
            return normalized[key]
    return None


def _external_features(
    esr_metrics: Any,
    abm_metrics: Any,
    as_of: pd.Timestamp,
) -> dict[str, float | str | None]:
    esr = _normalize_mapping(esr_metrics, as_of)
    abm = _normalize_mapping(abm_metrics, as_of)

    ssi = _fraction(
        _lookup(esr, "ssi", "ssi_pct", "systemic_stress_index", "stress_index")
    )
    esr_state_raw = _lookup(esr, "state", "regime", "market_state")
    esr_state = str(esr_state_raw) if esr_state_raw is not None else None

    vulnerability = _fraction(
        _lookup(
            abm,
            "vulnerability",
            "vulnerability_score",
            "system_vulnerability",
            "cascade_vulnerability",
        )
    )
    margin_distance = _fraction(
        _lookup(
            abm,
            "margin_distance",
            "margin_distance_pct",
            "distance_to_margin_call",
            "distance_to_margin_call_pct",
            "distance_to_cascade",
            "distance_to_cascade_pct",
        )
    )
    forced_share = _fraction(
        _lookup(abm, "forced_selling_share", "forced_liquidation_share", "liquidation_share")
    )
    panic_share = _fraction(
        _lookup(
            abm,
            "panic_share",
            "panic_rate",
            "panic_probability",
            "panic_pct",
            "panic_ratio_pct",
        )
    )
    orange_share = _fraction(_lookup(abm, "orange_share", "orange_pct", "orange"))
    red_share = _fraction(_lookup(abm, "red_share", "red_pct", "red"))
    stressed_share = None
    if orange_share is not None or red_share is not None:
        stressed_share = min(1.0, (orange_share or 0.0) + (red_share or 0.0))

    return {
        "esr_ssi": ssi,
        "esr_state": esr_state,
        "abm_vulnerability": vulnerability,
        "abm_margin_distance": margin_distance,
        "abm_forced_selling_share": forced_share,
        "abm_panic_share": panic_share,
        "abm_stressed_agent_share": stressed_share,
    }


def _dated_metric_frame(data: Any, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return only explicitly dated metric history available by ``as_of``.

    Scalar mappings are intentionally ignored here.  Broadcasting a current
    scalar backward would turn today's ABM state into look-ahead evidence for a
    prior liquidation session.
    """

    if isinstance(data, pd.DataFrame):
        frame = _as_datetime_index(data, "external metric history")
    elif isinstance(data, pd.Series) and isinstance(data.index, pd.DatetimeIndex):
        series = _as_datetime_index(data, "external metric history")
        frame = series.to_frame(name=str(data.name or "value"))
    elif isinstance(data, Mapping):
        dated: dict[str, pd.Series] = {}
        for key, value in data.items():
            if not isinstance(value, pd.Series) or not isinstance(value.index, pd.DatetimeIndex):
                continue
            dated[str(key)] = _as_datetime_index(value, f"external metric {key}")
        if not dated:
            return pd.DataFrame()
        frame = pd.concat(dated, axis=1)
    else:
        return pd.DataFrame()

    frame = frame.loc[:, ~frame.columns.duplicated(keep="last")]
    stamp = pd.Timestamp(as_of)
    if frame.index.tz is None and stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    elif frame.index.tz is not None and stamp.tzinfo is None:
        stamp = stamp.tz_localize(frame.index.tz)
    elif frame.index.tz is not None and stamp.tzinfo is not None:
        stamp = stamp.tz_convert(frame.index.tz)
    return frame.loc[frame.index <= stamp]


def _fraction_series(values: pd.Series | None) -> pd.Series | None:
    if values is None:
        return None
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    numeric = numeric.where(numeric >= 0)
    numeric = numeric.where(numeric <= 1.0, numeric / 100.0)
    return numeric.clip(lower=0.0, upper=1.0)


def _historical_abm_forced_evidence(
    abm_metrics: Any,
    market_index: pd.DatetimeIndex,
    *,
    as_of: pd.Timestamp,
    max_session_lag: int,
    config: CapitulationConfig,
) -> pd.Series:
    """Build a prior-only ABM forced-selling flag on the market calendar."""

    output = pd.Series(False, index=market_index, dtype=bool)
    frame = _dated_metric_frame(abm_metrics, as_of)
    if frame.empty:
        return output

    if market_index.tz is None and frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    elif market_index.tz is not None and frame.index.tz is None:
        frame.index = frame.index.tz_localize(market_index.tz)
    elif market_index.tz is not None and frame.index.tz is not None:
        frame.index = frame.index.tz_convert(market_index.tz)

    union = frame.index.union(market_index).sort_values()
    aligned = frame.reindex(union)
    session_lag = max(0, int(max_session_lag))
    if session_lag:
        aligned = aligned.ffill(limit=session_lag)
    aligned = aligned.reindex(market_index)
    normalized_columns = {
        str(column).lower().replace(" ", "_"): column for column in aligned.columns
    }

    def metric(*names: str) -> pd.Series | None:
        for name in names:
            column = normalized_columns.get(name.lower().replace(" ", "_"))
            if column is not None:
                return aligned[column]
        return None

    forced_share = _fraction_series(
        metric("forced_selling_share", "forced_liquidation_share", "liquidation_share")
    )
    vulnerability = _fraction_series(
        metric(
            "vulnerability",
            "vulnerability_score",
            "system_vulnerability",
            "cascade_vulnerability",
        )
    )
    margin_distance = _fraction_series(
        metric(
            "margin_distance",
            "margin_distance_pct",
            "distance_to_margin_call",
            "distance_to_margin_call_pct",
            "distance_to_cascade",
            "distance_to_cascade_pct",
        )
    )
    orange_share = _fraction_series(metric("orange_share", "orange_pct", "orange"))
    red_share = _fraction_series(metric("red_share", "red_pct", "red"))
    stressed_share = None
    if orange_share is not None or red_share is not None:
        stressed_share = pd.concat(
            [
                orange_share if orange_share is not None else pd.Series(np.nan, index=market_index),
                red_share if red_share is not None else pd.Series(np.nan, index=market_index),
            ],
            axis=1,
        ).sum(axis=1, min_count=1).clip(upper=1.0)

    if forced_share is not None:
        output |= forced_share.ge(config.abm_forced_share).fillna(False)
    if stressed_share is not None:
        output |= stressed_share.ge(config.abm_liquidation_share).fillna(False)
    if vulnerability is not None and margin_distance is not None:
        output |= (
            vulnerability.ge(config.abm_forced_vulnerability)
            & margin_distance.le(config.abm_margin_distance)
        ).fillna(False)
    return output.astype(bool)


class CapitulationRegimeEngine:
    """Compute point-in-time features and classify the current state."""

    def __init__(self, config: CapitulationConfig | None = None):
        self.config = config or CapitulationConfig()

    def analyze(
        self,
        index_close: pd.Series,
        constituent_close: pd.DataFrame,
        *,
        index_volume: pd.Series | None = None,
        constituent_volume: pd.DataFrame | None = None,
        esr_metrics: Any = None,
        abm_metrics: Any = None,
        as_of: Any | None = None,
    ) -> CapitulationSnapshot:
        index_series = _prepare_series(index_close, "index_close")
        stamp = _align_as_of(index_series.index, as_of)
        index_series = index_series.loc[index_series.index <= stamp]
        index_series = index_series.where(index_series > 0).dropna()
        if index_series.empty:
            raise ValueError("No index_close observation exists on or before as_of")
        stamp = index_series.index[-1]

        stocks = _prepare_frame(constituent_close, "constituent_close")
        stocks = stocks.loc[stocks.index <= stamp].where(stocks > 0)
        stocks = stocks.reindex(index_series.index).ffill(limit=self.config.max_price_ffill)
        stocks = stocks.dropna(axis=1, how="all")
        if stocks.empty:
            raise ValueError("No constituent prices exist on or before as_of")

        index_vol = None
        if index_volume is not None:
            index_vol = _prepare_series(index_volume, "index_volume")
            index_vol = index_vol.loc[index_vol.index <= stamp].reindex(index_series.index)

        stock_volumes = None
        if constituent_volume is not None:
            stock_volumes = _prepare_frame(constituent_volume, "constituent_volume")
            stock_volumes = stock_volumes.loc[stock_volumes.index <= stamp]
            stock_volumes = stock_volumes.reindex(index_series.index, columns=stocks.columns)

        features, percentiles, volume_source, volume_coverage = self._build_features(
            index_series, stocks, index_vol, stock_volumes
        )
        external = _external_features(esr_metrics, abm_metrics, stamp)
        abm_forced_history = _historical_abm_forced_evidence(
            abm_metrics,
            features.index,
            as_of=stamp,
            max_session_lag=self.config.external_metric_max_session_lag,
            config=self.config,
        )
        return self._snapshot(
            features,
            percentiles,
            external,
            abm_forced_history,
            stock_volumes,
            volume_source,
            volume_coverage,
        )

    def _build_features(
        self,
        index_close: pd.Series,
        stocks: pd.DataFrame,
        index_volume: pd.Series | None,
        stock_volumes: pd.DataFrame | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, str | None, float | None]:
        config = self.config
        frame = pd.DataFrame(index=index_close.index)
        frame["index_close"] = index_close
        frame["return_1d"] = index_close.pct_change(fill_method=None)
        frame["return_3d"] = index_close.pct_change(3, fill_method=None)
        frame["return_5d"] = index_close.pct_change(5, fill_method=None)

        log_close = np.log(index_close.where(index_close > 0))
        recent_pace = log_close.diff(3) / 3.0
        prior_pace = log_close.shift(3).diff(5) / 5.0
        frame["downside_acceleration"] = prior_pace - recent_pace
        frame["ma200_gap"] = index_close / index_close.rolling(
            config.index_ma_window, min_periods=config.index_ma_window
        ).mean() - 1.0
        frame["drawdown"] = index_close / index_close.cummax() - 1.0
        frame["constituent_count"] = stocks.notna().sum(axis=1).astype(float)
        frame["constituent_universe_size"] = float(stocks.shape[1])

        stock_returns = stocks.pct_change(fill_method=None)
        valid_returns = stock_returns.notna().sum(axis=1)
        enough_returns = valid_returns >= config.min_constituents
        frame["downside_participation"] = (stock_returns < 0).sum(axis=1).div(valid_returns)
        frame["severe_downside_participation"] = (
            stock_returns <= config.severe_downside_cutoff
        ).sum(axis=1).div(valid_returns)
        frame.loc[~enough_returns, ["downside_participation", "severe_downside_participation"]] = np.nan

        for window in config.ma_windows:
            moving_average = stocks.rolling(window, min_periods=window).mean()
            valid = stocks.notna() & moving_average.notna()
            denominator = valid.sum(axis=1)
            breadth = ((stocks > moving_average) & valid).sum(axis=1).div(denominator)
            frame[f"breadth_ma{window}"] = breadth.where(
                denominator >= config.min_constituents
            )
            frame[f"breadth_ma{window}_coverage"] = denominator.div(max(stocks.shape[1], 1))

        for label, window in (
            ("new_low_60", config.short_new_low_window),
            ("new_low_252", config.new_low_window),
        ):
            rolling_low = stocks.rolling(window, min_periods=window).min()
            valid = stocks.notna() & rolling_low.notna()
            denominator = valid.sum(axis=1)
            new_lows = ((stocks <= rolling_low) & valid).sum(axis=1).div(denominator)
            frame[label] = new_lows.where(denominator >= config.min_constituents)

        turnover = None
        turnover_coverage = pd.Series(np.nan, index=frame.index, dtype=float)
        volume_source = None
        volume_coverage = None
        if stock_volumes is not None:
            valid_volume = stock_volumes.gt(0) & stocks.notna()
            turnover_coverage = valid_volume.sum(axis=1).div(max(stocks.shape[1], 1))
            volume_coverage = float(turnover_coverage.iloc[-1])
            min_count = min(config.min_constituents, stocks.shape[1])
            turnover = (stocks * stock_volumes.where(stock_volumes > 0)).sum(
                axis=1, min_count=min_count
            )
            if turnover.notna().any():
                volume_source = "constituent_dollar_turnover"
        constituent_volume_reliable = bool(
            turnover is not None
            and pd.notna(turnover.iloc[-1])
            and volume_coverage is not None
            and volume_coverage >= config.min_breadth_coverage
        )
        if not constituent_volume_reliable and index_volume is not None:
            turnover = index_close * index_volume.where(index_volume > 0)
            turnover_coverage = index_volume.gt(0).astype(float)
            volume_source = "index_price_x_volume"
            volume_coverage = float(turnover_coverage.iloc[-1])

        if turnover is not None:
            frame["turnover"] = turnover
            frame["turnover_coverage"] = turnover_coverage
            frame["turnover_ratio_20"] = turnover / turnover.shift(1).rolling(20, min_periods=10).mean()
            frame["turnover_ratio_252"] = turnover / turnover.shift(1).rolling(
                252, min_periods=126
            ).mean()
            frame["selling_volume_shock"] = frame["turnover_ratio_20"].where(
                frame["return_1d"] < 0, 0.0
            )
        else:
            frame[
                [
                    "turnover",
                    "turnover_coverage",
                    "turnover_ratio_20",
                    "turnover_ratio_252",
                    "selling_volume_shock",
                ]
            ] = np.nan

        raw_for_percentiles: dict[str, tuple[str, bool]] = {
            "daily_loss": ("return_1d", False),
            "five_day_loss": ("return_5d", False),
            "downside_acceleration": ("downside_acceleration", True),
            "drawdown_stress": ("drawdown", False),
            "downside_participation": ("downside_participation", True),
            "severe_downside_participation": ("severe_downside_participation", True),
            "new_low_252": ("new_low_252", True),
            "selling_volume_shock": ("selling_volume_shock", True),
        }
        percentile_frame = pd.DataFrame(index=frame.index)
        for output_name, (source_name, higher_is_stress) in raw_for_percentiles.items():
            percentile_frame[output_name] = _prior_percentile(
                frame[source_name],
                higher_is_stress=higher_is_stress,
                lookback=config.percentile_lookback,
                min_history=config.percentile_min_history,
            )
        return frame, percentile_frame, volume_source, volume_coverage

    def _component_flags(
        self,
        features: pd.DataFrame,
        percentiles: pd.DataFrame,
    ) -> pd.DataFrame:
        config = self.config
        flags = pd.DataFrame(index=features.index)
        flags["price_shock"] = (
            (
                (features["return_1d"] <= config.price_shock_1d)
                & (percentiles["daily_loss"] >= config.shock_percentile)
            )
            | (
                (features["return_5d"] <= config.price_shock_5d)
                & (percentiles["five_day_loss"] >= config.shock_percentile)
            )
        ).fillna(False)
        flags["price_liquidation"] = (
            (features["return_1d"] <= config.liquidation_return_1d)
            | (features["return_5d"] <= config.liquidation_return_5d)
            | (
                (features["return_3d"] < 0)
                & (percentiles["downside_acceleration"] >= config.shock_percentile)
            )
        ).fillna(False)
        flags["breadth_shock"] = (
            (features["downside_participation"] >= config.downside_participation_shock)
            & (percentiles["downside_participation"] >= config.breadth_shock_percentile)
            & (
                (features["severe_downside_participation"] >= config.severe_downside_share)
                | (features["new_low_252"] >= config.new_low_share)
                | (features["breadth_ma20"] <= config.climax_breadth_ma20)
            )
        ).fillna(False)
        flags["breadth_liquidation"] = (
            (features["downside_participation"] >= 0.70)
            & (
                (percentiles["downside_participation"] >= 0.80)
                | (features["new_low_252"] >= 0.15)
            )
        ).fillna(False)
        flags["forced_selling_volume"] = (
            (features["return_1d"] < 0)
            & (features["turnover_coverage"] >= config.min_breadth_coverage)
            & (features["selling_volume_shock"] >= config.selling_volume_ratio)
            & (percentiles["selling_volume_shock"] >= config.breadth_shock_percentile)
        ).fillna(False)
        flags["core_climax"] = (
            flags["price_shock"] & flags["breadth_shock"] & flags["forced_selling_volume"]
        )
        flags["core_fragile"] = (
            (features["drawdown"] <= config.fragile_drawdown)
            | (features["ma200_gap"] <= 0.01)
        ) & (
            (features["breadth_ma20"] <= config.fragile_breadth)
            | (features["breadth_ma60"] <= config.fragile_breadth)
        )
        return flags.fillna(False)

    def _snapshot(
        self,
        features: pd.DataFrame,
        percentiles: pd.DataFrame,
        external: dict[str, float | str | None],
        abm_forced_history: pd.Series,
        stock_volumes: pd.DataFrame | None,
        volume_source: str | None,
        volume_coverage: float | None,
    ) -> CapitulationSnapshot:
        config = self.config
        current = features.iloc[-1]
        current_percentiles = percentiles.iloc[-1]
        flags = self._component_flags(features, percentiles)
        now_flags = flags.iloc[-1]
        abm_forced_history = abm_forced_history.reindex(features.index, fill_value=False)
        historical_climax = flags["core_climax"] | (
            flags["price_shock"] & flags["breadth_shock"] & abm_forced_history
        )

        esr_ssi = _finite_float(external["esr_ssi"])
        vulnerability = _finite_float(external["abm_vulnerability"])
        margin_distance = _finite_float(external["abm_margin_distance"])
        forced_share = _finite_float(external["abm_forced_selling_share"])
        stressed_agent_share = _finite_float(external["abm_stressed_agent_share"])
        panic_share = _finite_float(external["abm_panic_share"])

        abm_forced = bool(
            (forced_share is not None and forced_share >= config.abm_forced_share)
            or (stressed_agent_share is not None and stressed_agent_share >= config.abm_liquidation_share)
            or (
                vulnerability is not None
                and vulnerability >= config.abm_forced_vulnerability
                and margin_distance is not None
                and margin_distance <= config.abm_margin_distance
            )
        )
        esr_liquidation = esr_ssi is not None and esr_ssi >= config.esr_liquidation
        forced_evidence = bool(now_flags["forced_selling_volume"] or abm_forced)
        current_climax = bool(now_flags["price_shock"] and now_flags["breadth_shock"] and forced_evidence)

        structural_groups: list[tuple[str, bool]] = [
            (
                "price_structure",
                bool(
                    current["drawdown"] <= config.fragile_drawdown
                    or current["ma200_gap"] <= 0.01
                ),
            ),
            (
                "weak_breadth",
                bool(
                    current["breadth_ma20"] <= config.fragile_breadth
                    or current["breadth_ma60"] <= config.fragile_breadth
                ),
            ),
            (
                "turnover_dry_up",
                bool(
                    current["turnover_ratio_20"] <= config.fragile_turnover_ratio
                    or current["turnover_ratio_252"] <= config.fragile_turnover_ratio
                ),
            ),
            ("systemic_stress", esr_ssi is not None and esr_ssi >= config.esr_stress),
            (
                "agent_vulnerability",
                vulnerability is not None and vulnerability >= config.abm_vulnerability,
            ),
        ]
        active_structural = [name for name, active in structural_groups if active]
        fragile = len(active_structural) >= 2

        acute_groups = [
            bool(now_flags["price_liquidation"]),
            bool(now_flags["breadth_liquidation"]),
            forced_evidence,
            esr_liquidation,
        ]
        liquidation = sum(acute_groups) >= 2 and (
            bool(now_flags["price_liquidation"]) or bool(now_flags["breadth_liquidation"])
        )

        confirmation_reasons: list[str] = []
        exhaustion = False
        exhaustion_score = 0.0
        climax_offset = None
        if len(features) > 1:
            search_start = max(0, len(features) - 1 - config.exhaustion_lookback)
            prior_climax_positions = np.flatnonzero(
                historical_climax.iloc[search_start:-1].to_numpy(dtype=bool)
            )
            if prior_climax_positions.size:
                climax_position = search_start + int(prior_climax_positions[-1])
                climax_offset = len(features) - 1 - climax_position
                climax = features.iloc[climax_position]
                bounce = current["index_close"] / climax["index_close"] - 1.0
                positive_price = bool(
                    bounce >= config.exhaustion_min_bounce or current["return_1d"] >= 0.008
                )
                easing_checks = {
                    "downside participation receded": bool(
                        current["downside_participation"]
                        <= max(0.60, climax["downside_participation"] - 0.15)
                    ),
                    "new-low breadth diverged positively": bool(
                        climax["new_low_252"] > 0
                        and current["new_low_252"] <= climax["new_low_252"] * 0.75
                    ),
                    "MA20 breadth improved": bool(
                        current["breadth_ma20"] >= climax["breadth_ma20"] + 0.05
                    ),
                    "turnover shock normalized": bool(
                        pd.notna(climax["turnover_ratio_20"])
                        and current["turnover_ratio_20"] <= climax["turnover_ratio_20"] * 0.85
                    ),
                }
                passed = [reason for reason, condition in easing_checks.items() if condition]
                if positive_price:
                    confirmation_reasons.append(
                        f"price bounced {bounce:.1%} from climax close ({climax_offset} sessions ago)"
                    )
                confirmation_reasons.extend(passed)
                acute_pressure_cleared = not forced_evidence and not esr_liquidation
                exhaustion = (
                    positive_price
                    and len(passed) >= 2
                    and not current_climax
                    and acute_pressure_cleared
                )
                exhaustion_score = _weighted_score(
                    [(1.0 if positive_price else 0.0, 2.0)]
                    + [(1.0 if condition else 0.0, 1.0) for condition in easing_checks.values()]
                )

        recent_stress = bool(
            flags["core_fragile"].iloc[-config.repair_lookback : -1].any()
            or flags["price_liquidation"].iloc[-config.repair_lookback : -1].any()
        )
        index_ma20 = features["index_close"].rolling(20, min_periods=20).mean().iloc[-1]
        recovery_checks = [
            bool(pd.notna(index_ma20) and current["index_close"] > index_ma20),
            bool(current["breadth_ma20"] >= 0.45),
            bool(current["downside_participation"] <= 0.45),
            bool(current["return_5d"] >= 0.02),
        ]
        repair = recent_stress and sum(recovery_checks) >= 3 and not liquidation

        if current_climax:
            phase = CapitulationPhase.CAPITULATION_CLIMAX
        elif exhaustion:
            phase = CapitulationPhase.EXHAUSTION_CONFIRMED
        elif liquidation:
            phase = CapitulationPhase.LIQUIDATION
        elif repair:
            phase = CapitulationPhase.REPAIR
        elif fragile:
            phase = CapitulationPhase.FRAGILE
        else:
            phase = CapitulationPhase.NORMAL

        reasons: list[str] = []
        if now_flags["price_shock"]:
            reasons.append(
                f"price shock: 1d {current['return_1d']:.1%}, 5d {current['return_5d']:.1%}"
            )
        elif now_flags["price_liquidation"]:
            reasons.append(
                f"acute price pressure: 1d {current['return_1d']:.1%}, 5d {current['return_5d']:.1%}"
            )
        if now_flags["breadth_shock"]:
            reasons.append(
                "breadth shock: "
                f"{current['downside_participation']:.0%} declining, "
                f"{current['new_low_252']:.0%} at 252d lows"
            )
        elif now_flags["breadth_liquidation"]:
            reasons.append(
                f"broad downside participation: {current['downside_participation']:.0%}"
            )
        if now_flags["forced_selling_volume"]:
            reasons.append(f"down-day turnover shock: {current['turnover_ratio_20']:.2f}x 20d baseline")
        if abm_forced:
            reasons.append("ABM metrics indicate forced-selling pressure")
        if esr_liquidation:
            reasons.append(f"ESR systemic stress is acute ({esr_ssi:.0%})")
        elif esr_ssi is not None and esr_ssi >= config.esr_stress:
            reasons.append(f"ESR systemic stress is elevated ({esr_ssi:.0%})")
        if phase in {CapitulationPhase.FRAGILE, CapitulationPhase.NORMAL}:
            reasons.extend(active_structural)
        if phase == CapitulationPhase.EXHAUSTION_CONFIRMED:
            reasons.append("a prior three-gate climax has been followed by price and breadth confirmation")
        if phase == CapitulationPhase.REPAIR:
            reasons.append("trend and breadth repair followed recent stress")

        breadth_values = [
            _finite_float(current[f"breadth_ma{window}"]) for window in config.ma_windows
        ]
        valid_breadth = [value for value in breadth_values if value is not None]
        breadth_stress = None if not valid_breadth else 1.0 - float(np.mean(valid_breadth))
        drawdown_stress = _clip01((-current["drawdown"] - 0.03) / 0.17)
        ma_stress = _clip01((0.03 - current["ma200_gap"]) / 0.15)
        dryup_stress = _clip01((1.0 - current["turnover_ratio_20"]) / 0.50)
        stress_score = _weighted_score(
            [
                (drawdown_stress, 1.5),
                (ma_stress, 1.0),
                (breadth_stress, 2.0),
                (dryup_stress, 1.0),
                (esr_ssi, 1.0),
                (vulnerability, 1.0),
            ]
        )

        loss_severity = max(
            _clip01((-current["return_1d"] - 0.01) / 0.05) or 0.0,
            _clip01((-current["return_5d"] - 0.02) / 0.10) or 0.0,
            _finite_float(current_percentiles["daily_loss"]) or 0.0,
        )
        acceleration_severity = _finite_float(current_percentiles["downside_acceleration"])
        participation_severity = _clip01((current["downside_participation"] - 0.45) / 0.50)
        new_low_severity = _clip01(current["new_low_252"] / 0.50)
        volume_shock_severity = (
            _clip01((current["selling_volume_shock"] - 1.0) / 1.5)
            if current["return_1d"] < 0
            else 0.0
        )
        abm_liquidation_severity = max(
            forced_share or 0.0,
            stressed_agent_share or 0.0,
            panic_share or 0.0,
            (vulnerability or 0.0) * (1.0 if margin_distance is not None and margin_distance <= 0.05 else 0.5),
        )
        liquidation_score = _weighted_score(
            [
                (loss_severity, 2.0),
                (acceleration_severity, 1.0),
                (participation_severity, 1.5),
                (new_low_severity, 1.0),
                (volume_shock_severity, 1.5),
                (esr_ssi, 1.0),
                (abm_liquidation_severity, 1.0),
            ]
        )

        current_features: dict[str, float | str | None] = {
            key: _finite_float(value) for key, value in current.to_dict().items()
        }
        current_features.update(external)
        current_features["recent_climax_sessions_ago"] = (
            float(climax_offset) if climax_offset is not None else None
        )
        current_percentile_dict = {
            key: _finite_float(value) for key, value in current_percentiles.to_dict().items()
        }
        data_quality = self._data_quality(
            features,
            percentiles,
            current_features,
            stock_volumes,
            volume_source,
            volume_coverage,
        )

        required_gates = {
            "price_shock": bool(now_flags["price_shock"]),
            "breadth_shock": bool(now_flags["breadth_shock"]),
            "forced_selling": forced_evidence,
            "three_gate_climax": current_climax,
            "post_climax_exhaustion": exhaustion,
        }
        action_eligible = (
            phase is CapitulationPhase.EXHAUSTION_CONFIRMED
            and data_quality.status in {"GOOD", "LIMITED"}
        )

        return CapitulationSnapshot(
            as_of=features.index[-1],
            phase=phase,
            stress_risk_score_uncalibrated=stress_score,
            liquidation_risk_score_uncalibrated=liquidation_score,
            exhaustion_evidence_score_uncalibrated=exhaustion_score,
            features=current_features,
            percentiles=current_percentile_dict,
            required_gates_met=required_gates,
            trigger_reasons=tuple(dict.fromkeys(reasons)),
            confirmation_reasons=tuple(confirmation_reasons),
            data_quality=data_quality,
            action_eligible=action_eligible,
        )

    def _data_quality(
        self,
        features: pd.DataFrame,
        percentiles: pd.DataFrame,
        current_features: Mapping[str, Any],
        stock_volumes: pd.DataFrame | None,
        volume_source: str | None,
        volume_coverage: float | None,
    ) -> DataQuality:
        config = self.config
        current = features.iloc[-1]
        core_names = (
            "return_1d",
            "return_5d",
            "downside_acceleration",
            "ma200_gap",
            "drawdown",
            "breadth_ma20",
            "breadth_ma60",
            "breadth_ma125",
            "breadth_ma252",
            "downside_participation",
            "new_low_252",
            "turnover_ratio_20",
            "turnover_ratio_252",
        )
        available = tuple(name for name in core_names if pd.notna(current.get(name)))
        missing = tuple(name for name in core_names if pd.isna(current.get(name)))
        constituent_count = int(current.get("constituent_count", 0) or 0)
        breadth_coverage_value = _finite_float(current.get("breadth_ma252_coverage"))
        breadth_coverage = breadth_coverage_value or 0.0
        warnings: list[str] = []
        if len(features) < config.new_low_window:
            warnings.append(f"fewer than {config.new_low_window} index observations")
        if pd.isna(current["breadth_ma252"]):
            warnings.append("252-session breadth/new-low history is unavailable")
        elif breadth_coverage < config.min_breadth_coverage:
            warnings.append(
                f"current 252-session breadth coverage is below {config.min_breadth_coverage:.0%}"
            )
        if volume_source is None:
            warnings.append("turnover data is unavailable; volume cannot confirm forced selling")
        elif volume_coverage is not None and volume_coverage < 0.70:
            warnings.append("current constituent volume coverage is below 70%")
        percentile_available = int(percentiles.iloc[-1].notna().sum())
        if len(features) < config.percentile_min_history + 6 or percentile_available == 0:
            warnings.append("historical sample may be too short for stable tail percentiles")

        if (
            len(features) < config.index_ma_window
            or constituent_count < config.min_constituents
            or breadth_coverage < 0.50
        ):
            status = "INSUFFICIENT"
        elif warnings:
            status = "LIMITED"
        else:
            status = "GOOD"

        return DataQuality(
            status=status,
            index_observations=len(features),
            constituent_count=constituent_count,
            current_breadth_coverage=breadth_coverage,
            current_volume_coverage=volume_coverage,
            volume_source=volume_source,
            percentile_method=(
                "prior-only expanding empirical CDF"
                if config.percentile_lookback is None
                else f"prior-only rolling empirical CDF ({config.percentile_lookback} sessions)"
            ),
            available_features=available,
            missing_features=missing,
            warnings=tuple(warnings),
        )


def analyze_capitulation(
    index_close: pd.Series,
    constituent_close: pd.DataFrame,
    *,
    index_volume: pd.Series | None = None,
    constituent_volume: pd.DataFrame | None = None,
    esr_metrics: Any = None,
    abm_metrics: Any = None,
    as_of: Any | None = None,
    config: CapitulationConfig | None = None,
) -> CapitulationSnapshot:
    """Convenience wrapper around :class:`CapitulationRegimeEngine`."""

    return CapitulationRegimeEngine(config).analyze(
        index_close,
        constituent_close,
        index_volume=index_volume,
        constituent_volume=constituent_volume,
        esr_metrics=esr_metrics,
        abm_metrics=abm_metrics,
        as_of=as_of,
    )
