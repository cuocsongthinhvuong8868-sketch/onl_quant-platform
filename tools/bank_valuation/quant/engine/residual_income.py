import pandas as pd

def calculate_residual_income_value(adjusted_bvps: float, sustainable_roe: float, coe: float, assumptions: dict) -> float:
    """
    Compute intrinsic equity value per share using Residual Income Model.
    """
    if pd.isna(adjusted_bvps) or pd.isna(sustainable_roe) or pd.isna(coe):
        return float('nan')
        
    val_config = assumptions.get("valuation", {})
    years = val_config.get("forecast_years", 5)
    term_growth = val_config.get("terminal_growth", 0.045)
    payout_ratio = val_config.get("default_payout_ratio", 0.30)
    
    if coe <= term_growth:
        term_growth = max(0.0, coe - 0.01)
        
    value = adjusted_bvps
    current_bvps = adjusted_bvps
    
    for t in range(1, years + 1):
        net_income = sustainable_roe * current_bvps
        dividends = payout_ratio * net_income
        
        ri = (sustainable_roe - coe) * current_bvps
        discount_factor = (1 + coe) ** t
        value += (ri / discount_factor)
        
        current_bvps = current_bvps + net_income - dividends
        
    term_roe = coe + 0.01 
    terminal_ri = (term_roe - coe) * current_bvps
    terminal_value = terminal_ri / (coe - term_growth)
    
    discount_factor_term = (1 + coe) ** years
    value += (terminal_value / discount_factor_term)
    
    return max(0.0, value)
    
def calculate_justified_pb(sustainable_roe: float, coe: float, assumptions: dict, risk_scores: dict = None) -> float:
    """
    Justified P/B = (Sustainable ROE - Long-Term Growth) / (Cost of Equity - Long-Term Growth)
    """
    if pd.isna(sustainable_roe) or pd.isna(coe):
        return float('nan')
        
    val_config = assumptions.get("valuation", {})
    term_growth = val_config.get("terminal_growth", 0.045)
    
    if coe <= term_growth:
        term_growth = max(0.0, coe - 0.01)
        
    raw_pb = (sustainable_roe - term_growth) / (coe - term_growth)
    
    pb_adj_config = assumptions.get("pb_adjustments", {})
    if risk_scores is None:
        risk_scores = {}
        
    funding_score = risk_scores.get("funding_quality_score", 50.0)
    cc_score = risk_scores.get("credit_cycle_score", 50.0)
    col_score = risk_scores.get("collateral_risk_score", 50.0)
    cap_score = risk_scores.get("capital_dilution_risk_score", 50.0)
    
    funding_premium = (funding_score - 50.0) * pb_adj_config.get("funding_pb_sensitivity", 0.003)
    cc_discount = max(0.0, cc_score - 50.0) * pb_adj_config.get("credit_pb_discount_sensitivity", 0.004)
    col_discount = max(0.0, col_score - 50.0) * pb_adj_config.get("collateral_pb_discount_sensitivity", 0.003)
    cap_discount = max(0.0, cap_score - 50.0) * pb_adj_config.get("capital_pb_discount_sensitivity", 0.003)
    
    adjusted_pb = raw_pb + funding_premium - cc_discount - col_discount - cap_discount
    
    max_pb = val_config.get("max_justified_pb", 5.0)
    min_pb = val_config.get("min_justified_pb", 0.2)
    
    return max(min_pb, min(max_pb, adjusted_pb))
