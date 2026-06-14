import pandas as pd
from tools.bank_valuation.quant.engine.utils import safe_divide

def calculate_core_metrics(row: pd.Series) -> dict:
    """
    Calculate core metrics from a normalized row.
    If the raw data already has them (e.g. roe), use it. Otherwise, calculate.
    """
    metrics = {}
    
    # 1. ROE
    if "roe" in row and not pd.isna(row["roe"]):
        metrics["reported_roe"] = float(row["roe"])
    else:
        net_income = row.get("net_profit_after_tax", float('nan'))
        equity = row.get("equity", float('nan'))
        metrics["reported_roe"] = safe_divide(net_income, equity)
        
    # 2. ROA
    if "roa" in row and not pd.isna(row["roa"]):
        metrics["roa"] = float(row["roa"])
    else:
        net_income = row.get("net_profit_after_tax", float('nan'))
        assets = row.get("total_assets", float('nan'))
        metrics["roa"] = safe_divide(net_income, assets)
        
    # 3. P/B
    if "pb" in row and not pd.isna(row["pb"]):
        metrics["market_pb"] = float(row["pb"])
    else:
        price = row.get("price", float('nan'))
        bvps = row.get("book_value_per_share", float('nan'))
        metrics["market_pb"] = safe_divide(price, bvps)

    # 4. NIM proxy
    nii = row.get("net_interest_income", float('nan'))
    assets = row.get("total_assets", float('nan'))
    metrics["nim_proxy"] = safe_divide(nii, assets)
    
    # 5. Credit Cost
    if "credit_cost" in row and not pd.isna(row["credit_cost"]):
        metrics["credit_cost"] = abs(float(row["credit_cost"]))
    else:
        provision = row.get("provision_expense", float('nan'))
        loans = row.get("customer_loans", float('nan'))
        if not pd.isna(provision):
            provision = abs(provision)
        metrics["credit_cost"] = safe_divide(provision, loans)
    
    # 6. NPL Ratio & Provision Coverage
    llr = row.get("loan_loss_reserve", float('nan'))
    npl_balance = row.get("npl_balance", float('nan'))
    loans = row.get("customer_loans", float('nan'))
    
    npl_ratio = row.get("npl_ratio", float('nan'))
    if pd.isna(npl_ratio) and not pd.isna(npl_balance):
        npl_ratio = safe_divide(npl_balance, loans)
    metrics["npl_ratio"] = npl_ratio
    
    if "provision_coverage" in row and not pd.isna(row["provision_coverage"]):
        metrics["provision_coverage"] = abs(float(row["provision_coverage"]))
    else:
        # if NPL ratio is provided but not NPL balance, estimate NPL balance
        if pd.isna(npl_balance) and not pd.isna(npl_ratio) and not pd.isna(loans):
            npl_balance = npl_ratio * loans
        if not pd.isna(llr):
            llr = abs(llr)
        metrics["provision_coverage"] = safe_divide(llr, npl_balance)
        
    # 7. Group 2 Ratio
    group2_balance = row.get("group2_loans", float('nan'))
    if not pd.isna(group2_balance):
        metrics["group2_ratio"] = safe_divide(group2_balance, loans)
    elif "group2_ratio" in row and not pd.isna(row["group2_ratio"]):
        # Special Mentioned might be raw number, if it's not a ratio but raw balance:
        val = float(row["group2_ratio"])
        if val > 1: # means it's an absolute balance
            metrics["group2_ratio"] = safe_divide(val, loans)
        else:
            metrics["group2_ratio"] = val
    else:
        metrics["group2_ratio"] = float('nan')
    
    # 8. CASA Ratio
    casa = row.get("casa_balance", float('nan'))
    deposits = row.get("customer_deposits", float('nan'))
    metrics["casa_ratio"] = safe_divide(casa, deposits)
    
    # 9. LDR
    if "ldr" in row and not pd.isna(row["ldr"]):
        metrics["ldr"] = float(row["ldr"])
    else:
        metrics["ldr"] = safe_divide(loans, deposits)
    
    # 10. CAR & CET1 Proxy
    car = row.get("car", float('nan'))
    if not pd.isna(car) and car <= 0:
        car = float('nan')
    if not pd.isna(car) and car < 0.01:
        car = float('nan')
    metrics["car"] = car
    metrics["cet1_proxy"] = car * 0.8 if not pd.isna(car) else float('nan')
    metrics["warnings"] = ""
    
    return metrics
