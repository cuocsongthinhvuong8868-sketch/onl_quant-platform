import pandas as pd
from tools.bank_valuation.quant.engine.adjusted_book import calculate_adjusted_book_value
from tools.bank_valuation.quant.engine.roe_engine import calculate_sustainable_roe
from tools.bank_valuation.quant.engine.cost_of_equity import calculate_cost_of_equity
from tools.bank_valuation.quant.engine.residual_income import calculate_residual_income_value, calculate_justified_pb

def run_scenario_valuation(row: pd.Series, history_df: pd.DataFrame, metrics: dict, risk_scores: dict, assumptions: dict) -> dict:
    """
    Run valuation across all 4 scenarios.
    """
    results = {}
    
    for scenario in ["bull", "base", "bear", "stress"]:
        scen_metrics = metrics.copy()
        
        adj_book = calculate_adjusted_book_value(row, scen_metrics, assumptions.get("credit", {}), scenario=scenario)
        sust_roe = calculate_sustainable_roe(row, history_df, scen_metrics, assumptions, scenario=scenario)
        coe = calculate_cost_of_equity(risk_scores, assumptions)
        
        justified_pb = calculate_justified_pb(sust_roe, coe, assumptions, risk_scores)
        
        pb_risk_discount = assumptions.get("scenarios", {}).get(scenario, {}).get("pb_risk_discount", 0.0)
        
        if not pd.isna(justified_pb):
            justified_pb = max(0.0, justified_pb - pb_risk_discount)
        
        bvps = adj_book["adjusted_book_value_per_share"]
        rim_value = calculate_residual_income_value(bvps, sust_roe, coe, assumptions)
        
        if not pd.isna(justified_pb) and not pd.isna(bvps):
            pb_value = justified_pb * bvps
        else:
            pb_value = float('nan')
            
        results[scenario] = {
            "reported_equity": adj_book["reported_equity"],
            "adjusted_equity": adj_book["adjusted_equity"],
            "book_value_per_share": adj_book["book_value_per_share"],
            "tangible_book_value_per_share": adj_book["tangible_book_value_per_share"],
            "adjusted_bvps": bvps,
            "sustainable_roe": sust_roe,
            "normalized_roe": scen_metrics.get("normalized_roe", float('nan')),
            "stress_adjusted_roe": scen_metrics.get("stress_adjusted_roe", float('nan')),
            "cost_of_equity": coe,
            "justified_pb": justified_pb,
            "fair_value_rim": rim_value,
            "fair_value_pb": pb_value,
            "adjustments": adj_book.get("adjustments", {}),
            "warnings": adj_book.get("warnings", [])
        }
        
    return results
