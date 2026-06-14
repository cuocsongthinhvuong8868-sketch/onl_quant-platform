import pandas as pd

def calculate_final_scores_and_classification(risk_scores: dict, valuation_gap: float, stress_downside: float) -> dict:
    """
    Combine all risk scores and classify the stock.
    """
    credit = risk_scores.get("credit_cycle_score", 50.0)
    collat = risk_scores.get("collateral_risk_score", 50.0)
    cap = risk_scores.get("capital_dilution_risk_score", 50.0)
    fund = risk_scores.get("funding_quality_score", 50.0)
    
    inv_fund = 100.0 - fund
    
    overall = (0.35 * credit) + (0.25 * collat) + (0.25 * cap) + (0.15 * inv_fund)
    
    cls = "Neutral / Need More Data"
    
    if not pd.isna(valuation_gap) and not pd.isna(stress_downside):
        if valuation_gap > 0.25 and overall < 40 and stress_downside > -0.20:
            cls = "Strong Undervalued"
        elif valuation_gap > 0.20 and (overall > 70 or stress_downside < -0.35):
            cls = "Value Trap Warning"
        elif valuation_gap > 0.25 and overall >= 40:
            cls = "Undervalued but Risky"
        elif -0.10 <= valuation_gap <= 0.25:
            cls = "Fairly Valued"
        elif valuation_gap < -0.10:
            cls = "Overvalued"
            
    return {
        "overall_risk_score": overall,
        "classification": cls
    }
