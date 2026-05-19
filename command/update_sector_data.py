"""
update_sector_data.py — Cào ICB sector classification từ vnstock free tier.

Output: data_lake/ticker_metadata.csv
  Columns: Ticker, industry_code, industry_name, exchange

Idempotent: chạy lại sẽ overwrite. Không incremental vì sector ít đổi.
Pairs trading dùng để sanity-check predefined cluster + sector-based filter.

Usage:
    python command/update_sector_data.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_LAKE, TICKERS_FILE

METADATA_FILE = DATA_LAKE / "ticker_metadata.csv"


def fetch_sector_mapping() -> pd.DataFrame:
    """Fetch ticker → ICB industry từ vnstock Listing().symbols_by_industries().

    Returns DF với cols [symbol, industry_code, industry_name].
    """
    from vnstock import Listing

    logger.info("Fetching ICB sector mapping từ vnstock Listing...")
    df = Listing().symbols_by_industries()
    logger.info("✓ Lấy được %d ticker × %d cột", df.shape[0], df.shape[1])
    return df


def fetch_exchange_mapping() -> dict[str, str]:
    """Fetch exchange per ticker (HOSE/HNX/UPCOM).

    Iterate qua các exchange group và build dict. Free tier OK.
    """
    from vnstock import Listing

    exchanges = {"HOSE", "HNX", "UPCOM"}
    out: dict[str, str] = {}
    for ex in exchanges:
        try:
            logger.info("Fetching exchange list: %s ...", ex)
            df = Listing().symbols_by_exchange()
            if "symbol" in df.columns and "exchange" in df.columns:
                for _, row in df.iterrows():
                    out[str(row["symbol"]).strip().upper()] = str(row["exchange"]).strip()
                logger.info("✓ %d ticker từ symbols_by_exchange (toàn bộ)", len(out))
                return out  # function returns full list 1 lần, break loop
        except Exception as exc:
            logger.warning("Exchange fetch %s lỗi: %s", ex, exc)
    return out


def build_metadata() -> pd.DataFrame:
    """Combine sector + exchange info, restrict to tickers trong tickers.csv.

    Output schema: index=Ticker, cols=[industry_code, industry_name, exchange]
    """
    sector_df = fetch_sector_mapping()
    sector_df.columns = [c.lower() for c in sector_df.columns]
    sector_df["symbol"] = sector_df["symbol"].str.strip().str.upper()

    # User's universe filter
    our_tickers = (
        pd.read_csv(TICKERS_FILE)["Ticker"].dropna().str.strip().str.upper().tolist()
    )
    logger.info("Universe trong tickers.csv: %d mã", len(our_tickers))

    df = sector_df[sector_df["symbol"].isin(our_tickers)].copy()
    df = df.drop_duplicates(subset="symbol", keep="first")
    df = df.rename(columns={"symbol": "Ticker"}).set_index("Ticker")

    # Exchange enrichment (best effort)
    try:
        ex_map = fetch_exchange_mapping()
        df["exchange"] = df.index.map(lambda t: ex_map.get(t, "UNKNOWN"))
    except Exception as exc:
        logger.warning("Exchange enrichment skip: %s", exc)
        df["exchange"] = "UNKNOWN"

    # Report coverage
    missing = set(our_tickers) - set(df.index)
    if missing:
        logger.warning(
            "%d ticker trong tickers.csv KHÔNG có sector mapping: %s",
            len(missing),
            sorted(missing)[:10],
        )

    logger.info("Sector coverage: %d / %d = %.1f%%",
                len(df), len(our_tickers), 100 * len(df) / len(our_tickers))
    return df


def save_metadata(df: pd.DataFrame) -> None:
    DATA_LAKE.mkdir(parents=True, exist_ok=True)
    df.to_csv(METADATA_FILE)
    logger.info("✓ Saved → %s (%d rows × %d cols)", METADATA_FILE, *df.shape)


def main() -> None:
    df = build_metadata()
    save_metadata(df)
    logger.info("Done. Sample:\n%s", df.head(5).to_string())


if __name__ == "__main__":
    main()
