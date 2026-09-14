"""Validated market-data snapshot and execution-readiness gates."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DataQualityReport:
    as_of: pd.Timestamp
    fingerprint: str
    rows: int
    tickers: int
    nonpositive_cells_removed: int
    duplicate_dates_removed: int
    volume_masked_cells: int
    adjusted_verified: bool
    point_in_time_universe: bool
    warnings: tuple[str, ...] = ()


@dataclass
class MarketDataSnapshot:
    prices: pd.DataFrame
    volumes: pd.DataFrame | None
    quality: DataQualityReport
    metadata: pd.DataFrame | None = None

    def pair_prices(self, t1: str, t2: str, *, min_obs: int = 60) -> pd.DataFrame:
        if t1 == t2 or t1 not in self.prices or t2 not in self.prices:
            raise ValueError(f"Pair không hợp lệ hoặc thiếu ticker: {t1}/{t2}")
        pair = self.prices[[t1, t2]].dropna(how="any")
        if len(pair) < min_obs:
            raise ValueError(f"{t1}/{t2} chỉ có {len(pair)} common observations")
        return pair

    def liquidity(self, ticker: str, window: int = 20) -> dict:
        if self.volumes is None or ticker not in self.volumes or ticker not in self.prices:
            return {"adv_vnd": None, "median_volume": None, "available": False}
        aligned = pd.concat(
            [self.prices[ticker].rename("price"), self.volumes[ticker].rename("volume")], axis=1
        ).dropna().tail(window)
        aligned = aligned[(aligned["price"] > 0) & (aligned["volume"] > 0)]
        if aligned.empty:
            return {"adv_vnd": None, "median_volume": None, "available": False}
        return {
            # vnstock equity close is stored in thousand VND.
            "adv_vnd": float((aligned["price"] * 1_000.0 * aligned["volume"]).median()),
            "median_volume": float(aligned["volume"].median()),
            "available": True,
        }


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    reasons: tuple[str, ...]
    data_as_of: str
    common_quote_as_of: str | None
    adv_1_vnd: float | None
    adv_2_vnd: float | None
    checks: dict[str, bool] = field(default_factory=dict)


def _fingerprint(*frames: tuple[str, pd.DataFrame | None]) -> str:
    """Content fingerprint covering full research inputs, not just their tail."""
    digest = hashlib.sha256()
    for label, frame in frames:
        digest.update(label.encode())
        if frame is None:
            digest.update(b"none")
            continue
        digest.update(str(frame.shape).encode())
        digest.update("\x1f".join(map(str, frame.columns)).encode())
        if not frame.empty:
            digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()[:16]


def build_market_data_snapshot(
    prices: pd.DataFrame,
    volumes: pd.DataFrame | None = None,
    metadata: pd.DataFrame | None = None,
    *,
    adjusted_verified: bool = False,
    point_in_time_universe: bool = False,
    mask_stale_quotes_with_volume: bool = True,
) -> MarketDataSnapshot:
    """Sanitize numeric prices and mask stale/suspended quotes where volume is reliable."""
    if prices.empty:
        raise ValueError("Market price data rỗng")
    numeric = prices.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    duplicates = int(numeric.index.duplicated(keep="last").sum())
    numeric = numeric.loc[~numeric.index.duplicated(keep="last")].sort_index()
    nonpositive = int((numeric <= 0).sum().sum())
    numeric = numeric.where(numeric > 0)
    cleaned_volumes: pd.DataFrame | None = None
    masked = 0
    if volumes is not None and not volumes.empty:
        cleaned_volumes = volumes.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        cleaned_volumes = cleaned_volumes.loc[~cleaned_volumes.index.duplicated(keep="last")].sort_index()
        cleaned_volumes = cleaned_volumes.reindex(index=numeric.index, columns=numeric.columns)
        if mask_stale_quotes_with_volume:
            for ticker in numeric.columns:
                quoted = numeric[ticker].notna()
                if not quoted.any():
                    continue
                active = cleaned_volumes[ticker].fillna(0) > 0
                coverage = float(active[quoted].mean())
                # Only trust volume as a stale-quote mask when the source covers the ticker.
                if coverage >= 0.8:
                    stale = quoted & ~active
                    masked += int(stale.sum())
                    numeric.loc[stale, ticker] = np.nan
    warnings: list[str] = []
    if nonpositive:
        warnings.append(f"Removed {nonpositive} non-positive price cells.")
    if not adjusted_verified:
        warnings.append("Adjusted-price provenance is not verified.")
    if not point_in_time_universe:
        warnings.append("Universe/sector metadata is current-state, not point-in-time.")
    as_of = pd.Timestamp(numeric.index.max())
    quality = DataQualityReport(
        as_of=as_of,
        fingerprint=_fingerprint(
            ("prices", numeric),
            ("volumes", cleaned_volumes),
            ("metadata", metadata),
        ),
        rows=int(numeric.shape[0]),
        tickers=int(numeric.shape[1]),
        nonpositive_cells_removed=nonpositive,
        duplicate_dates_removed=duplicates,
        volume_masked_cells=masked,
        adjusted_verified=bool(adjusted_verified),
        point_in_time_universe=bool(point_in_time_universe),
        warnings=tuple(warnings),
    )
    return MarketDataSnapshot(
        prices=numeric,
        volumes=cleaned_volumes,
        quality=quality,
        metadata=metadata.copy() if metadata is not None else None,
    )


def _business_session_age(as_of: pd.Timestamp, today: date | None = None) -> int:
    current = pd.Timestamp(today or date.today()).normalize()
    start = pd.Timestamp(as_of).normalize()
    if start >= current:
        return 0
    return int(np.busday_count(start.date(), current.date()))


def assess_execution_readiness(
    snapshot: MarketDataSnapshot,
    t1: str,
    t2: str,
    *,
    model_as_of: pd.Timestamp | str | None,
    adjusted_override: bool = False,
    borrow_confirmed: bool = False,
    foreign_room_verified: bool = False,
    shortable: bool = False,
    min_adv_vnd: float = 1_000_000_000.0,
    max_data_age_sessions: int = 2,
) -> ExecutionReadiness:
    reasons: list[str] = []
    try:
        pair = snapshot.pair_prices(t1, t2)
        common_as_of = pd.Timestamp(pair.index.max())
    except ValueError as exc:
        reasons.append(str(exc))
        common_as_of = None
    adjusted_ok = bool(snapshot.quality.adjusted_verified or adjusted_override)
    if not adjusted_ok:
        reasons.append("Chưa xác minh giá adjusted cho corporate actions")
    age = _business_session_age(snapshot.quality.as_of)
    fresh = age <= max_data_age_sessions
    if not fresh:
        reasons.append(f"Market data stale {age} business sessions")
    common_current = bool(common_as_of is not None and common_as_of == snapshot.quality.as_of)
    if not common_current:
        reasons.append("Hai leg không có common quote ở data-as-of")
    if not borrow_confirmed:
        reasons.append("Chưa xác nhận borrow inventory/fee")
    if not shortable:
        reasons.append("Short leg chưa được xác nhận đủ điều kiện")
    if not foreign_room_verified:
        reasons.append("Chưa xác minh foreign room/FOL")
    liquidity_1, liquidity_2 = snapshot.liquidity(t1), snapshot.liquidity(t2)
    adv_1, adv_2 = liquidity_1["adv_vnd"], liquidity_2["adv_vnd"]
    liquidity_ok = bool(adv_1 is not None and adv_2 is not None and min(adv_1, adv_2) >= min_adv_vnd)
    if not liquidity_ok:
        reasons.append(f"Một leg thiếu ADV hoặc ADV < {min_adv_vnd:,.0f} VND")
    model_current = bool(model_as_of and pd.Timestamp(model_as_of).normalize() == snapshot.quality.as_of.normalize())
    if not model_current:
        reasons.append("Model fit không cùng as-of với market data")
    checks = {
        "adjusted_price_verified": adjusted_ok,
        "fresh_data": fresh,
        "common_quote": common_current,
        "borrow_confirmed": bool(borrow_confirmed),
        "short_leg_is_shortable": bool(shortable),
        "foreign_room_verified": bool(foreign_room_verified),
        "liquidity_ok": liquidity_ok,
        "model_current": model_current,
    }
    return ExecutionReadiness(
        ready=not reasons,
        reasons=tuple(reasons),
        data_as_of=snapshot.quality.as_of.strftime("%Y-%m-%d"),
        common_quote_as_of=common_as_of.strftime("%Y-%m-%d") if common_as_of is not None else None,
        adv_1_vnd=adv_1,
        adv_2_vnd=adv_2,
        checks=checks,
    )
