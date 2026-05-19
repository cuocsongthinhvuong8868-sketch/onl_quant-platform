"""
clusters.py — Predefined cointegrated VN cluster cho pairs_trading.

Rule khi update:
- Cùng economic/regulatory driver (cùng sector, cùng input cost, cùng FOL regime).
- 3-6 ticker per cluster: <3 không có cointegration vector room; >6 Johansen instability.
- MBB là Quân Đội Bank (commercial), nhóm Private_Bank (not SOE Big4).
- BSR/PVS có thể UPCOM → graceful skip nếu không có trong market_data.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PREDEFINED_CLUSTERS: dict[str, list[str]] = {
    "Vingroup":     ["VIC", "VHM", "VRE"],
    "Big4_Bank":    ["VCB", "CTG", "BID"],                              # SOE only (3-way Johansen)
    "Steel":        ["HPG", "HSG", "NKG"],
    "Securities":   ["SSI", "HCM", "VND", "VCI"],
    "Private_Bank": ["VPB", "STB", "ACB", "SHB", "MBB", "HDB"],         # 6-way commercial bank
    "Oil_Gas":      ["GAS", "PLX", "BSR", "PVS"],
    "Utility":      ["REE", "GEX", "POW", "HDG"],
}

CLUSTER_DESCRIPTIONS: dict[str, str] = {
    "Vingroup":     "Same parent (Vingroup), shared FII flow, real estate",
    "Big4_Bank":    "SOE bank: regulated rate, NIM cycle, deposit base",
    "Steel":        "Iron ore + rebar/galvanized cycle, China import competition",
    "Securities":   "Brokerage commission cycle, retail margin loan",
    "Private_Bank": "Retail loan book, NIM compression — FOL risk on VPB/STB",
    "Oil_Gas":      "Brent crude link, USD/VND, refinery margin",
    "Utility":      "Capacity factor, El Niño cycle, regulated tariff",
}


def get_cluster(name: str) -> list[str]:
    """Return ticker list cho cluster. KeyError nếu name không tồn tại."""
    if name not in PREDEFINED_CLUSTERS:
        raise KeyError(f"Cluster '{name}' không tồn tại. Available: {list(PREDEFINED_CLUSTERS)}")
    return PREDEFINED_CLUSTERS[name].copy()


def list_clusters() -> list[str]:
    return list(PREDEFINED_CLUSTERS.keys())


def validate_clusters_against_universe(available_tickers: set[str]) -> dict[str, list[str]]:
    """Filter cluster tickers to those available trong market_data.csv columns.

    Returns dict[cluster_name] -> [available tickers].
    Warn-on-miss vì UPCOM ticker (BSR/PVS) có thể không có.
    """
    out: dict[str, list[str]] = {}
    for cluster, tickers in PREDEFINED_CLUSTERS.items():
        present = [t for t in tickers if t in available_tickers]
        missing = [t for t in tickers if t not in available_tickers]
        if missing:
            logger.warning(
                "Cluster %s: skip missing tickers %s (probably UPCOM/delisted)",
                cluster, missing,
            )
        if len(present) >= 2:
            out[cluster] = present
        else:
            logger.warning("Cluster %s: chỉ %d ticker available, drop cluster", cluster, len(present))
    return out
