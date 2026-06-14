import pandas as pd

def calculate_sustainable_roe(row: pd.Series, history_df: pd.DataFrame, metrics: dict, assumptions: dict, scenario: str = "base") -> float:
    """
    Calculate sustainable ROE using weighted average of latest normalized ROE,
    3Y median ROE, and stress-adjusted ROE.
    """
    reported_roe = metrics.get("reported_roe", float('nan'))
    normalized_roe = reported_roe
    
    # Calculate normalized ROE
    reported_credit_cost = metrics.get("credit_cost", 0.0)
    if pd.isna(reported_credit_cost):
        reported_credit_cost = 0.0
    else:
        reported_credit_cost = abs(reported_credit_cost)
        
    loans = row.get("customer_loans", float('nan'))
    equity = row.get("equity", float('nan'))
    
    credit_assumptions = assumptions.get("credit", {})
    if not pd.isna(reported_roe) and not pd.isna(loans) and not pd.isna(equity) and equity > 0:
        credit_cost_floor = credit_assumptions.get(f"credit_cost_floor_{scenario}", 0.008)
        normalized_credit_cost = max(reported_credit_cost, credit_cost_floor)
        # A floor penalizes under-provisioning but does not reward a bank for
        # reporting credit cost above the floor.
        excess_credit_cost = reported_credit_cost - normalized_credit_cost
        tax_rate = 0.20
        # roe_adjustment will be negative if reported < normalized
        roe_adjustment = excess_credit_cost * (loans / equity) * (1 - tax_rate)
        normalized_roe = reported_roe + roe_adjustment
        
    metrics["normalized_roe"] = normalized_roe
    
    three_year_median_roe = reported_roe
    if history_df is not None and not history_df.empty and "roe" in history_df.columns:
        recent_roes = history_df["roe"].dropna().tail(12)
        if not recent_roes.empty:
            three_year_median_roe = recent_roes.median()
            
    # Stress-adjusted ROE
    nim_shock = assumptions.get("scenarios", {}).get(scenario, {}).get("nim_shock", 0.0)
    cc_shock = assumptions.get("scenarios", {}).get(scenario, {}).get("credit_cost_shock", 0.0)
    
    assets = row.get("total_assets", float('nan'))
    equity_multiplier = (assets / equity) if (not pd.isna(assets) and not pd.isna(equity) and equity > 0) else 10.0
    
    stress_impact = (nim_shock - cc_shock) * equity_multiplier * 0.8
    stress_adjusted_roe = normalized_roe + stress_impact
    metrics["stress_adjusted_roe"] = stress_adjusted_roe
    
    weights = assumptions.get("sustainable_roe_weights", {})
    w_latest = weights.get("latest_normalized_roe", 0.40)
    w_median = weights.get("three_year_median_roe", 0.40)
    w_stress = weights.get("stress_adjusted_roe", 0.20)
    
    # Handle NaNs gracefully
    if pd.isna(normalized_roe): w_latest = 0.0
    if pd.isna(three_year_median_roe): w_median = 0.0
    if pd.isna(stress_adjusted_roe): w_stress = 0.0
    
    total_w = w_latest + w_median + w_stress
    if total_w == 0:
        sustainable_roe = float('nan')
    else:
        sustainable_roe = ((w_latest * (normalized_roe if not pd.isna(normalized_roe) else 0)) + 
                           (w_median * (three_year_median_roe if not pd.isna(three_year_median_roe) else 0)) + 
                           (w_stress * (stress_adjusted_roe if not pd.isna(stress_adjusted_roe) else 0))) / total_w
                           
    metrics["sustainable_roe"] = sustainable_roe
    
    return sustainable_roe
