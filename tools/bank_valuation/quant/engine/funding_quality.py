import pandas as pd

def calculate_funding_quality_score(row: pd.Series, metrics: dict) -> dict:
    """
    Score 0-100 (higher means BETTER funding quality).
    """
    score = 50.0
    
    casa = metrics.get("casa_ratio", float('nan'))
    ldr = metrics.get("ldr", float('nan'))
    
    casa_score = 50
    if not pd.isna(casa):
        if casa > 0.3: casa_score = 90
        elif casa < 0.15: casa_score = 20
        else: casa_score = 50
        
    ldr_score = 50
    if not pd.isna(ldr):
        if ldr < 0.8: ldr_score = 90
        elif ldr > 1.0: ldr_score = 20
        else: ldr_score = 50
        
    if not pd.isna(casa) and not pd.isna(ldr):
        score = 0.6 * casa_score + 0.4 * ldr_score
    elif not pd.isna(casa):
        score = casa_score
    elif not pd.isna(ldr):
        score = ldr_score
        
    return {"funding_quality_score": score}
