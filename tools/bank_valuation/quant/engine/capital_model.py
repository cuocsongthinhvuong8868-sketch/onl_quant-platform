import pandas as pd

def calculate_capital_dilution_risk(row: pd.Series, metrics: dict, assumptions: dict) -> dict:
    """
    Score 0-100 (higher means MORE dilution risk).
    """
    score = 50.0
    
    car = metrics.get("car", float('nan'))
    roe = metrics.get("sustainable_roe", metrics.get("reported_roe", float('nan')))
    
    if pd.isna(roe):
        roe = 0.15 # fallback for calculation
        
    val_config = assumptions.get("valuation", {})
    payout = val_config.get("default_payout_ratio", 0.30)
    retention = 1.0 - payout
    
    sust_growth = roe * retention
    expected_loan_growth = 0.15 
    
    growth_gap = expected_loan_growth - sust_growth
    
    car_score = 50
    if not pd.isna(car):
        if car > 0.12: car_score = 20
        elif car < 0.09: car_score = 90
        else: car_score = 50
        
    gap_score = 50
    if not pd.isna(growth_gap):
        if growth_gap < 0: gap_score = 20
        elif growth_gap > 0.05: gap_score = 80
        else: gap_score = 50
        
    if not pd.isna(car) and not pd.isna(growth_gap):
        score = 0.6 * car_score + 0.4 * gap_score
    elif not pd.isna(car):
        score = car_score
    else:
        score = gap_score
        
    return {"capital_dilution_risk_score": score}
