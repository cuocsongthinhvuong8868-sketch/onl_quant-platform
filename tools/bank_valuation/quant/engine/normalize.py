import pandas as pd

ACCOUNT_ALIASES = {
    "equity": [
        "equity",
        "shareholders_equity",
        "total_equity",
        "total equity",
        "owner's equity",
        "vốn chủ sở hữu",
        "von_chu_so_huu"
    ],
    "customer_loans": [
        "loans_to_customers",
        "customer_loans",
        "loans and advances to customers",
        "cho vay khách hàng",
        "cho_vay_khach_hang"
    ],
    "customer_deposits": [
        "customer_deposits",
        "deposits_from_customers",
        "deposits from customers",
        "tiền gửi khách hàng",
        "tien_gui_khach_hang"
    ],
    "npl_ratio": [
        "npl_ratio",
        "bad_debt_ratio",
        "tỷ lệ nợ xấu",
        "ty_le_no_xau"
    ],
    "market_cap": [
        "Market Cap",
        "market_cap",
        "vốn hóa"
    ],
    "shares_outstanding": [
        "Outstanding Shares",
        "shares_outstanding",
        "khối lượng niêm yết"
    ],
    "pb": [
        "PB",
        "p_b",
        "p/b",
        "price_to_book"
    ],
    "roe": [
        "ROE (%)",
        "roe",
        "roe_pct"
    ],
    "roa": [
        "ROA (%)",
        "roa",
        "roa_pct"
    ],
    "net_profit_after_tax": [
        "net_profit",
        "net profit after tax",
        "net profit/(loss) after tax",
        "lợi nhuận sau thuế",
        "npat"
    ],
    "total_assets": [
        "total_assets",
        "total assets",
        "tổng tài sản"
    ],
    "group2_ratio": [
        "group2_ratio",
        "group 2 ratio",
        "special mentioned ratio"
    ],
    "group2_loans": [
        "group2_loans",
        "group 2 loans",
        "special mentioned"
    ],
    "casa_balance": [
        "casa_balance",
        "current deposits",
        "tiền gửi không kỳ hạn"
    ],
    "car": [
        "car",
        "hệ số an toàn vốn"
    ],
    "loan_loss_reserve": [
        "loan_loss_reserve",
        "less: provision for losses on loans and advances to customers",
        "dự phòng rủi ro tín dụng"
    ],
    "credit_cost": [
        "credit_cost",
        "provision to outstanding loans (%)"
    ],
    "provision_coverage": [
        "provision_coverage",
        "loan loss reserves/npls (%)"
    ],
    "ldr": [
        "ldr (%)",
        "ldr"
    ],
    "npl_ratio": [
        "npl_ratio",
        "npl ratio (%)",
        "bad_debt_ratio",
        "tỷ lệ nợ xấu",
        "ty_le_no_xau"
    ],
    "npl_balance": [
        "npl_balance",
        "non-performing loans",
        "non performing loans"
    ],
    "net_interest_income": [
        "net interest income",
        "thu nhập lãi thuần"
    ],
    "total_operating_income": [
        "total operating income",
        "tổng thu nhập hoạt động"
    ],
    "operating_expense": [
        "operating expenses",
        "chi phí hoạt động"
    ],
    "provision_expense": [
        "provision for credit losses",
        "chi phí dự phòng rủi ro tín dụng"
    ],
    "intangible_assets": [
        "intangible fixed assets"
    ],
    "goodwill": [
        "in which: goodwill"
    ]
}

def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')

def _abs_numeric(df: pd.DataFrame, col: str) -> None:
    if col in df.columns:
        df[col] = _to_numeric(df[col]).abs()

def normalize_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names based on aliases."""
    if df.empty:
        return df
        
    normalized_df = df.copy()
    
    # Invert mapping for easier lookup
    alias_to_std = {}
    for std_name, aliases in ACCOUNT_ALIASES.items():
        for alias in aliases:
            alias_to_std[alias.lower()] = std_name
            
    # Rename columns if they match an alias
    rename_mapping = {}
    pct_cols = []
    
    for orig_col in normalized_df.columns:
        col_lower = orig_col.lower()
        if "(%)" in col_lower or "pct" in col_lower:
            pct_cols.append(orig_col)
            
        if col_lower in alias_to_std:
            rename_mapping[orig_col] = alias_to_std[col_lower]
            
    normalized_df.rename(columns=rename_mapping, inplace=True)
    
    # Auto-convert percentage columns (identified by original name) to decimals.
    # parse_number strips a trailing "%" but leaves the number in percentage
    # points, so the conversion belongs here where the metric name is known.
    for orig_col in pct_cols:
        col_name = rename_mapping.get(orig_col, orig_col)
        if col_name in normalized_df.columns:
            values = _to_numeric(normalized_df[col_name])
            normalized_df[col_name] = values / 100.0
            
    if "shares_outstanding" in normalized_df.columns:
        shares = _to_numeric(normalized_df["shares_outstanding"])
        max_abs = shares.abs().max(skipna=True)
        if pd.notna(max_abs) and max_abs > 1e6:
            shares = shares / 1e9
        normalized_df["shares_outstanding"] = shares

    if "car" in normalized_df.columns:
        car = _to_numeric(normalized_df["car"])
        nonzero_car = car[(car.notna()) & (car != 0)]
        max_abs = nonzero_car.abs().max(skipna=True)
        if pd.notna(max_abs) and max_abs < 1e-6:
            car = car * 1e9
        elif pd.notna(max_abs) and max_abs > 1.0:
            car = car / 100.0
        normalized_df["car"] = car

    # Financial statements often store reserves/provisions as contra-asset or
    # expense lines with a negative sign. Valuation formulas need positive loss
    # amounts and positive coverage ratios.
    for col in ["loan_loss_reserve", "provision_coverage", "provision_expense", "credit_cost"]:
        _abs_numeric(normalized_df, col)

    # Build NPL balance from grading buckets when the raw file discloses them.
    grading_cols = [c for c in ["Substandard", "Doubtful", "Bad"] if c in normalized_df.columns]
    if grading_cols:
        derived_npl = normalized_df[grading_cols].apply(pd.to_numeric, errors='coerce').sum(axis=1, min_count=1)
        if "npl_balance" not in normalized_df.columns:
            normalized_df["npl_balance"] = derived_npl
        else:
            current = _to_numeric(normalized_df["npl_balance"])
            normalized_df["npl_balance"] = current.fillna(derived_npl)

    if "npl_ratio" in normalized_df.columns and "npl_balance" in normalized_df.columns and "customer_loans" in normalized_df.columns:
        npl_ratio = _to_numeric(normalized_df["npl_ratio"])
        loans = _to_numeric(normalized_df["customer_loans"])
        normalized_df["npl_ratio"] = npl_ratio.fillna(normalized_df["npl_balance"] / loans)
                 
    return normalized_df
