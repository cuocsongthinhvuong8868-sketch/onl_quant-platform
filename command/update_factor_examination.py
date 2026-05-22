"""
command/update_factor_examination.py — Daily pre-warm Factor Examination pkl cache.

Compute scoring với default sidebar params (sector_neutral=True/False, min_adv=1.0 tỷ),
save pkl qua shared/daily_cache.py. Pkl được commit qua update_pipeline.yml workflow
→ Cloud rebuild thấy pkl mới → render Factor Exam page hit pkl ngay (không recompute).

KHÔNG compute IC backtest (~30-60s) — chỉ scoring (~5s).
KHÔNG gọi AI — đây là compute-only refresh, AI run on-demand qua UI button.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.daily_cache import save_daily_cache
from shared.data_loader import (
    load_close_prices,
    load_custom,
    load_ticker_metadata,
    load_volumes,
)
from tools.factor_examination.quant.factors import compute_all_factors
from tools.factor_examination.quant.scoring import build_score_table

EXCLUDE_PATTERNS = ("FUEV", "FUET", "E1VFVN30", "VN30F")
DEFAULT_MIN_ADV_BILLION = 1.0
SCORE_NAMESPACE = "factor_examination"
METHOD_V = "v1"


def _build_universe(prices, volumes, min_adv_billion: float) -> list[str]:
    cols = [c for c in prices.columns if not any(c.startswith(p) for p in EXCLUDE_PATTERNS)]
    if min_adv_billion <= 0 or len(prices) < 20:
        return cols
    dollar_vol = (prices[cols] * volumes[cols]).iloc[-20:]
    median_dv = dollar_vol.median() / 1e6
    return median_dv[median_dv >= min_adv_billion].index.tolist()


def main() -> int:
    prices = load_close_prices()
    volumes = load_volumes()
    if volumes is None:
        print("❌ market_volume.csv không tồn tại — skip factor_examination prewarm.")
        return 0

    vnindex = load_custom("vnindex_cache.csv")["VNINDEX"]
    metadata = load_ticker_metadata()
    market = vnindex.reindex(prices.index).ffill()

    data_date = str(prices.index[-1].date())
    print(f"📅 Data date: {data_date}")

    universe = sorted(_build_universe(prices, volumes, DEFAULT_MIN_ADV_BILLION))
    print(f"🌐 Universe: {len(universe)} tickers (min_adv={DEFAULT_MIN_ADV_BILLION} tỷ)")

    if len(universe) < 30:
        print(f"❌ Universe quá nhỏ ({len(universe)}<30) — skip.")
        return 0

    prices_u = prices[universe]
    volumes_u = volumes[universe]

    for sector_neutral in (True, False):
        cache_key = {
            "universe": universe,
            "sector_neutral": sector_neutral,
            "method_v": METHOD_V,
        }
        factors = compute_all_factors(prices_u, volumes_u, market)
        scored = build_score_table(factors, metadata, sector_neutral=sector_neutral)
        path = save_daily_cache(SCORE_NAMESPACE, cache_key, scored, data_date=data_date)
        size_kb = path.stat().st_size // 1024
        print(f"  💾 sector_neutral={sector_neutral}: {path.name} ({size_kb} KB)")

    print("✅ Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
