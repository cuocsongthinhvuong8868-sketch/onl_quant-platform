import pandas as pd


def calculate_cost_of_equity(risk_scores: dict, assumptions: dict) -> float:
    """
    Calculate bank-specific required return (Cost of Equity).
    """
    val_config = assumptions.get("valuation", {})
    risk_free = val_config.get("risk_free_rate", 0.045)
    beta = risk_scores.get("beta", val_config.get("default_beta", 1.10))
    if pd.isna(beta) or beta <= 0:
        beta = val_config.get("default_beta", 1.10)
    erp = val_config.get("market_erp", 0.081)
    
    cc_score = risk_scores.get("credit_cycle_score", 50.0)
    cap_score = risk_scores.get("capital_dilution_risk_score", 50.0)
    col_score = risk_scores.get("collateral_risk_score", 50.0)
    
    rp_config = assumptions.get("risk_premium", {})
    cc_max = rp_config.get("credit_cycle_risk_premium_max", 0.020)
    cap_max = rp_config.get("capital_risk_premium_max", 0.015)
    col_max = rp_config.get("collateral_risk_premium_max", 0.020)
    gov_default = rp_config.get("governance_risk_premium_default", 0.005)
    
    cc_premium = (cc_score / 100.0) * cc_max
    cap_premium = (cap_score / 100.0) * cap_max
    col_premium = (col_score / 100.0) * col_max
    
    bank_specific_premium = cc_premium + cap_premium + col_premium + gov_default
    
    coe = risk_free + (beta * erp) + bank_specific_premium
    return coe
