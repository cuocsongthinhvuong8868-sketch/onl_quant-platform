from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class ValuationOutput:
    ticker: str
    period: str
    price: float = float('nan')
    beta: float = float('nan')
    shares_outstanding: float = float('nan')
    reported_equity: float = float('nan')
    adjusted_equity: float = float('nan')
    book_value_per_share: float = float('nan')
    adjusted_book_value_per_share: float = float('nan')
    tangible_book_value_per_share: float = float('nan')
    reported_roe: float = float('nan')
    normalized_roe: float = float('nan')
    sustainable_roe: float = float('nan')
    stress_adjusted_roe: float = float('nan')
    cost_of_equity: float = float('nan')
    justified_pb: float = float('nan')
    market_pb: float = float('nan')
    fair_value_per_share_rim: float = float('nan')
    fair_value_per_share_pb: float = float('nan')
    stress_value_per_share: float = float('nan')
    valuation_gap_pct: float = float('nan')
    npl_ratio: float = float('nan')
    group2_ratio: float = float('nan')
    credit_cost: float = float('nan')
    provision_coverage: float = float('nan')
    casa_ratio: float = float('nan')
    ldr: float = float('nan')
    car: float = float('nan')
    car_source: str = ""
    car_disclosure_date: str = ""
    cet1_proxy: float = float('nan')
    capital_dilution_risk_score: float = float('nan')
    credit_cycle_score: float = float('nan')
    funding_quality_score: float = float('nan')
    collateral_risk_score: float = float('nan')
    overall_risk_score: float = float('nan')
    classification: str = "Neutral / Need More Data"
    peer_median_pb: float = float('nan')
    peer_median_roe: float = float('nan')
    roe_adjusted_fair_pb: float = float('nan')
    market_mispricing_score: float = float('nan')
    relative_valuation_label: str = "Relative Value Unavailable"
    relative_value_warning: str = ""
    data_quality_flag: str = "Medium"
    confidence_score: float = 100.0
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str):
        self.warnings.append(message)
        self.confidence_score = max(0.0, self.confidence_score - 5.0)

    def to_dict(self):
        return {
            "ticker": self.ticker,
            "period": self.period,
            "price": self.price,
            "beta": self.beta,
            "shares_outstanding": self.shares_outstanding,
            "reported_equity": self.reported_equity,
            "adjusted_equity": self.adjusted_equity,
            "book_value_per_share": self.book_value_per_share,
            "adjusted_book_value_per_share": self.adjusted_book_value_per_share,
            "tangible_book_value_per_share": self.tangible_book_value_per_share,
            "reported_roe": self.reported_roe,
            "normalized_roe": self.normalized_roe,
            "sustainable_roe": self.sustainable_roe,
            "stress_adjusted_roe": self.stress_adjusted_roe,
            "cost_of_equity": self.cost_of_equity,
            "justified_pb": self.justified_pb,
            "market_pb": self.market_pb,
            "fair_value_per_share_rim": self.fair_value_per_share_rim,
            "fair_value_per_share_pb": self.fair_value_per_share_pb,
            "stress_value_per_share": self.stress_value_per_share,
            "valuation_gap_pct": self.valuation_gap_pct,
            "npl_ratio": self.npl_ratio,
            "group2_ratio": self.group2_ratio,
            "credit_cost": self.credit_cost,
            "provision_coverage": self.provision_coverage,
            "casa_ratio": self.casa_ratio,
            "ldr": self.ldr,
            "car": self.car,
            "car_source": self.car_source,
            "car_disclosure_date": self.car_disclosure_date,
            "cet1_proxy": self.cet1_proxy,
            "capital_dilution_risk_score": self.capital_dilution_risk_score,
            "credit_cycle_score": self.credit_cycle_score,
            "funding_quality_score": self.funding_quality_score,
            "collateral_risk_score": self.collateral_risk_score,
            "overall_risk_score": self.overall_risk_score,
            "classification": self.classification,
            "peer_median_pb": self.peer_median_pb,
            "peer_median_roe": self.peer_median_roe,
            "roe_adjusted_fair_pb": self.roe_adjusted_fair_pb,
            "market_mispricing_score": self.market_mispricing_score,
            "relative_valuation_label": self.relative_valuation_label,
            "relative_value_warning": self.relative_value_warning,
            "data_quality_flag": self.data_quality_flag,
            "confidence_score": self.confidence_score,
            "warnings": "; ".join(self.warnings)
        }
