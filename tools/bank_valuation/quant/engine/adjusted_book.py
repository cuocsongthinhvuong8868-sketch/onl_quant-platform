import pandas as pd

def calculate_adjusted_book_value(row: pd.Series, metrics: dict = None, credit_assumptions: dict = None, scenario: str = "base") -> dict:
    """
    Input: standardized bank financial row + metrics + credit scenario assumptions.
    Output: adjusted book value components.
    """
    # Backward compatibility for the older call shape:
    # calculate_adjusted_book_value(row, credit_assumptions, "base")
    if isinstance(credit_assumptions, str):
        scenario = credit_assumptions
        credit_assumptions = metrics if isinstance(metrics, dict) else {}
        metrics = {}

    if metrics is None:
        metrics = {}
    if credit_assumptions is None:
        credit_assumptions = {}

    warnings = []
    reported_equity = row.get("equity", float('nan'))
    intangibles = row.get("intangible_assets", 0.0)
    goodwill = row.get("goodwill", 0.0)
    
    if pd.isna(intangibles):
        intangibles = 0.0
        warnings.append("intangible_assets missing; assumed zero")
    if pd.isna(goodwill):
        goodwill = 0.0
        warnings.append("goodwill missing; assumed zero")
    
    tangible_equity = reported_equity - intangibles - goodwill
    
    loans = row.get("customer_loans", 0.0)
    if pd.isna(loans): loans = 0.0
    
    # Under-provisioning adjustment
    npl_balance = row.get("npl_balance", float('nan'))
    if pd.isna(npl_balance):
        npl_ratio = metrics.get("npl_ratio", row.get("npl_ratio", float('nan')))
        if pd.isna(npl_ratio):
            npl_balance = 0.0
            warnings.append("npl_balance and npl_ratio missing; under-provisioning adjustment skipped")
        else:
            npl_balance = npl_ratio * loans
            warnings.append("npl_balance missing; estimated from npl_ratio and customer_loans")
    
    llr = row.get("loan_loss_reserve", float('nan'))
    if not pd.isna(llr):
        llr = abs(llr)
    else:
        provision_coverage = metrics.get("provision_coverage", row.get("provision_coverage", float('nan')))
        if pd.isna(provision_coverage):
            provision_coverage = 0.0
            warnings.append("loan_loss_reserve and provision_coverage missing; assumed zero reserve")
        llr = abs(provision_coverage) * npl_balance
    
    target_coverage = credit_assumptions.get(f"target_provision_coverage_{scenario}", 1.0)
    required_provisions = npl_balance * target_coverage
    under_provisioning = max(0.0, required_provisions - llr)
    
    # Hidden NPL adjustment
    group2_loans = row.get("group2_loans", float('nan'))
    if pd.isna(group2_loans):
        group2_ratio = metrics.get("group2_ratio", row.get("group2_ratio", float('nan')))
        if pd.isna(group2_ratio):
            group2_loans = 0.0
            warnings.append("group2 loans missing; hidden NPL adjustment skipped")
        elif group2_ratio > 1:
            group2_loans = group2_ratio
        else:
            group2_loans = group2_ratio * loans
    
    migration_rate = credit_assumptions.get(f"group2_to_npl_migration_{scenario}", 0.15)
    lgd = credit_assumptions.get(f"lgd_{scenario}", 0.35)
    
    hidden_npl_proxy = group2_loans * migration_rate
    hidden_npl_loss = hidden_npl_proxy * lgd
    
    collateral_haircut = 0.0
    
    adjusted_equity = reported_equity - intangibles - goodwill - under_provisioning - hidden_npl_loss - collateral_haircut
    
    shares = row.get("shares_outstanding", float('nan'))
    if pd.isna(shares) or shares == 0:
        shares = float('nan')
        warnings.append("shares_outstanding missing or zero; per-share book values unavailable")
        
    return {
        "reported_equity": reported_equity,
        "adjusted_equity": adjusted_equity,
        "book_value_per_share": reported_equity / shares if not pd.isna(shares) else float('nan'),
        "tangible_book_value_per_share": tangible_equity / shares if not pd.isna(shares) else float('nan'),
        "adjusted_book_value_per_share": adjusted_equity / shares if not pd.isna(shares) else float('nan'),
        "adjustments": {
            "intangibles": intangibles,
            "goodwill": goodwill,
            "under_provisioning": under_provisioning,
            "hidden_npl_loss": hidden_npl_loss,
            "collateral_haircut": collateral_haircut
        },
        "warnings": warnings
    }
