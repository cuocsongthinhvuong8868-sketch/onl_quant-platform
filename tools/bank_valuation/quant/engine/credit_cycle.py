import pandas as pd

def calculate_credit_cycle_score(row: pd.Series, metrics: dict) -> dict:
    """
    Absolute threshold scoring for credit cycle if peer data is unavailable.
    Score 0-100 (lower is better).
    """
    score = 50.0 
    
    npl = row.get("npl_ratio", metrics.get("npl_ratio", float('nan')))
    group2 = row.get("group2_ratio", metrics.get("group2_ratio", float('nan')))
    cov = metrics.get("provision_coverage", float('nan'))
    cc = metrics.get("credit_cost", float('nan'))
    
    npl_score = 50
    if not pd.isna(npl):
        if npl < 0.015: npl_score = 20
        elif npl > 0.03: npl_score = 90
        else: npl_score = 50
        
    group2_score = 50
    if not pd.isna(group2):
        if group2 < 0.015: group2_score = 20
        elif group2 > 0.03: group2_score = 90
        else: group2_score = 50
        
    cov_score = 50
    if not pd.isna(cov):
        if cov > 1.0: cov_score = 20
        elif cov < 0.5: cov_score = 90
        else: cov_score = 50
        
    cc_score = 50
    if not pd.isna(cc):
        if cc < 0.01: cc_score = 20
        elif cc > 0.02: cc_score = 90
        else: cc_score = 50
        
    available_scores = []
    if not pd.isna(npl): available_scores.append(npl_score)
    if not pd.isna(group2): available_scores.append(group2_score)
    if not pd.isna(cov): available_scores.append(cov_score)
    if not pd.isna(cc): available_scores.append(cc_score)
    
    if available_scores:
        score = sum(available_scores) / len(available_scores)
        
    label = "moderate risk"
    if score < 30: label = "low risk"
    elif score > 80: label = "stress"
    elif score > 60: label = "high risk"
        
    return {
        "credit_cycle_score": score,
        "credit_cycle_label": label
    }
