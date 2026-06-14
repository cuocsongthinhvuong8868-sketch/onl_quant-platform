import pandas as pd
import numpy as np

def safe_divide(numerator: float, denominator: float, default: float = float('nan')) -> float:
    """Safely divide two numbers, returning default if denominator is zero or nan."""
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return default
    return float(numerator / denominator)

def parse_number(val) -> float:
    """Parse string numbers with formats like 36.873T, 1.08B, or just numeric."""
    if pd.isna(val):
        return float('nan')
    if isinstance(val, (int, float)):
        return float(val)
    
    val = str(val).strip().upper()
    if not val:
        return float('nan')
    
    is_percent = val.endswith('%')
    if is_percent:
        val = val[:-1].strip()

    is_parenthesized_negative = val.startswith('(') and val.endswith(')')
    if is_parenthesized_negative:
        val = val[1:-1].strip()

    multiplier = 1.0
    if val.endswith('T'):
        multiplier = 1e12
        val = val[:-1]
    elif val.endswith('B'):
        multiplier = 1e9
        val = val[:-1]
    elif val.endswith('M'):
        multiplier = 1e6
        val = val[:-1]
    
    # remove commas
    val = val.replace(',', '')
    try:
        parsed = float(val) * multiplier
        if is_parenthesized_negative:
            parsed = -parsed
        return parsed
    except ValueError:
        return float('nan')
