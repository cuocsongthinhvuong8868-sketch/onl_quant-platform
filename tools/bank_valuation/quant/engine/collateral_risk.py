import pandas as pd

def calculate_collateral_risk_score(row: pd.Series, metrics: dict) -> dict:
    """
    Score 0-100 (higher means more collateral risk).
    """
    score = 50.0
    
    npl = row.get("npl_ratio", metrics.get("npl_ratio", float('nan')))
    cov = metrics.get("provision_coverage", float('nan'))
    
    if not pd.isna(npl) and not pd.isna(cov):
        if npl > 0.03 and cov < 0.5:
            score = 85.0
        elif npl < 0.015 and cov > 1.0:
            score = 20.0
        else:
            score = 50.0
            
    return {"collateral_risk_score": score}
