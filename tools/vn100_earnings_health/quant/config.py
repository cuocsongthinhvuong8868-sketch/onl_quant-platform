from pathlib import Path

from config import AI_PROVIDER_MAP, AI_TEMPERATURE, DATA_LAKE, ROOT_DIR

PROJECT_ROOT = ROOT_DIR
TOOL_DATA_DIR = DATA_LAKE / "vn100_earnings_health"
RAW_JSON_DIR = TOOL_DATA_DIR / "bctc_json" / "json"
OUTPUT_DIR = TOOL_DATA_DIR / "outputs"
PROMPT_DIR = ROOT_DIR / "promt"
AI_CACHE_DIR = DATA_LAKE / "daily_cache"

DEFAULT_WINSOR_LOWER = 0.05
DEFAULT_WINSOR_UPPER = 0.95
DEFAULT_ROLLING_WINDOW = 12
CFO_TO_LNST_THRESHOLD = 0.80
HIGH_STRESS_THRESHOLD = 70.0
MIN_SECTOR_OBS = 3

FINANCIAL_SECTORS = {"Banks", "Financial Services", "Insurance"}
BANK_SECTORS = {"Banks"}
SECURITIES_SECTORS = {"Financial Services"}
INSURANCE_SECTORS = {"Insurance"}

CORE_COLUMNS = [
    "growth_score",
    "profitability_score",
    "cash_conversion_score",
    "working_capital_stress_score",
    "balance_sheet_resilience_score",
    "capital_allocation_score",
]

HEALTH_CORE_COLUMNS = [
    "growth_score",
    "profitability_score",
    "cash_conversion_score",
    "balance_sheet_resilience_score",
    "capital_allocation_score",
]

STRESS_COLUMNS = [
    "working_capital_stress_score",
    "leverage_stress_score",
]

CORE_PAIR_EXPECTATIONS = {
    ("growth_score", "profitability_score"): 1,
    ("profitability_score", "cash_conversion_score"): 1,
    ("growth_score", "working_capital_stress_score"): -1,
    ("cash_conversion_score", "balance_sheet_resilience_score"): 1,
    ("growth_score", "capital_allocation_score"): 1,
    ("profitability_score", "balance_sheet_resilience_score"): 1,
}

DISPLAY_CORE_NAMES = {
    "growth_score": "Growth",
    "profitability_score": "Profitability",
    "cash_conversion_score": "Cash Conversion",
    "working_capital_stress_score": "WC Stress",
    "balance_sheet_resilience_score": "Balance Sheet",
    "capital_allocation_score": "Capital Allocation",
    "leverage_stress_score": "Leverage Stress",
    "matrix_consistency_score": "Matrix Consistency",
    "corporate_health_score": "Corporate Health",
}

CANONICAL_MAPPINGS = {
    "revenue": [
        ("Income Statement", "Net sales"),
        ("Income Statement", "OPERATING SALES"),
        ("Income Statement", "Net sales from insurance business"),
        ("Income Statement", "Total Operating Income"),
        ("Income Statement", "Interest and Similar Income"),
        ("Income Statement", "Sales"),
    ],
    "cost_of_sales": [
        ("Income Statement", "Cost of sales"),
        ("Income Statement", "OPERATING EXPENSE"),
        ("Income Statement", "Total direct insurance operating expenses"),
        ("Income Statement", "Interest and Similar Expenses"),
    ],
    "gross_profit": [
        ("Income Statement", "Gross Profit"),
        ("Income Statement", "GROSS PROFIT"),
        ("Income Statement", "Gross insurance operating profit"),
        ("Income Statement", "Net Interest Income"),
    ],
    "ebit": [
        ("Income Statement", "Operating profit/(loss)"),
        ("Income Statement", "OPERATING PROFIT/(LOSS)"),
        ("Income Statement", "Net Operating Profit Before Allowance for Credit Loss"),
        ("Income Statement", "Net operating profit from insurance operation"),
    ],
    "net_profit": [
        ("Income Statement", "Net profit/(loss) after tax"),
        ("Income Statement", "NET PROFIT/(LOSS) AFTER TAX"),
        ("Income Statement", "Attributable to parent company"),
        ("Income Statement", "Net profit attributable to shareholders of the group"),
        ("Income Statement", "Net profit/(loss) after tax of parent company"),
    ],
    "interest_expense": [
        ("Income Statement", "Interest expenses"),
        ("Income Statement", "Interests expenses"),
        ("Income Statement", "Interest and Similar Expenses"),
        ("Cash Flow", "Interest expense"),
    ],
    "cash": [
        ("Balance Sheet", "Cash and cash equivalents"),
        ("Balance Sheet", "Cash and precious metals"),
        ("Balance Sheet", "CASH AND CASH EQUIVALENT"),
        ("Balance Sheet", "Cash"),
    ],
    "current_assets": [
        ("Balance Sheet", "CURRENT ASSETS"),
        ("Balance Sheet", "Current assets"),
    ],
    "total_assets": [
        ("Balance Sheet", "Total Assets"),
        ("Balance Sheet", "TOTAL ASSETS"),
    ],
    "receivables": [
        ("Balance Sheet", "Accounts receivable"),
        ("Balance Sheet", "Trade accounts receivable"),
        ("Balance Sheet", "Other receivables"),
        ("Balance Sheet", "SHORT-TERM RECEIVABLES FROM SECURITIES TRADING"),
    ],
    "inventory": [
        ("Balance Sheet", "Inventories, Net"),
        ("Balance Sheet", "Inventories"),
        ("Balance Sheet", "Inventory"),
    ],
    "payables": [
        ("Balance Sheet", "Trade accounts payable"),
        ("Balance Sheet", "Accounts payable"),
        ("Balance Sheet", "Payables for securities trading"),
    ],
    "short_term_debt": [
        ("Balance Sheet", "Short-term borrowings"),
        ("Balance Sheet", "Short-term loans and liabilities"),
        ("Balance Sheet", "SHORT-TERM LOANS AND LIABILITIES"),
        ("Balance Sheet", "Short-term borrowings and Short-term liabilities"),
    ],
    "long_term_debt": [
        ("Balance Sheet", "Long-term borrowings"),
        ("Balance Sheet", "Long-term borrowings and liabilities"),
        ("Balance Sheet", "LONG-TERM LIABILITIES"),
    ],
    "liabilities": [
        ("Balance Sheet", "Liabilities"),
        ("Balance Sheet", "LIABILITIES"),
        ("Balance Sheet", "TOTAL LIABILITIES"),
    ],
    "current_liabilities": [
        ("Balance Sheet", "Current liabilities"),
        ("Balance Sheet", "Current Liabilities"),
    ],
    "equity": [
        ("Balance Sheet", "Owner's Equity"),
        ("Balance Sheet", "OWNER'S EQUITY"),
        ("Balance Sheet", "Owners' equity"),
        ("Balance Sheet", "Owner's equity"),
    ],
    "fixed_assets": [
        ("Balance Sheet", "Fixed assets"),
        ("Balance Sheet", "Tangible fixed assets"),
    ],
    "cfo": [
        ("Cash Flow", "Net cash inflows/(outflows) from operating activities"),
        ("Cash Flow", "Net cash from operating activities"),
        ("Cash Flow", "Net cash flows from operating activities before CIT"),
    ],
    "capex": [
        ("Cash Flow", "Purchases of fixed assets and other long term assets"),
        ("Cash Flow", "Payments on disposal of fixed assets"),
    ],
    "depreciation": [
        ("Cash Flow", "Depreciation and amortization"),
    ],
    "investing_cashflow": [
        ("Cash Flow", "Net cash inflows/(outflows) from investing activities"),
        ("Cash Flow", "Net cash from investing activities"),
    ],
    "financing_cashflow": [
        ("Cash Flow", "Net cash inflows/(outflows) from financing activities"),
        ("Cash Flow", "Net cash from financing activities"),
    ],
}
