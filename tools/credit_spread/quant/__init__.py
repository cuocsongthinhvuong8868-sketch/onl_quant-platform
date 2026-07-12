"""Quantitative calculations for the credit-spread monitor."""

from tools.credit_spread.quant.metrics import (
    calculate_benchmark_spreads,
    calculate_credit_spread,
    load_aggregated_yields,
    load_government_yields,
    load_issuance_data,
)

__all__ = [
    "calculate_benchmark_spreads",
    "calculate_credit_spread",
    "load_aggregated_yields",
    "load_government_yields",
    "load_issuance_data",
]
