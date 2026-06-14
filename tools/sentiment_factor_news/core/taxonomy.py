# Macro Sentiment Taxonomy definitions

MACRO_CHANNELS = [
    "growth",
    "inflation",
    "monetary_policy",
    "liquidity",
    "credit_stress",
    "fx_external",
    "fiscal_public_investment",
    "real_estate_collateral",
    "banking_system",
    "risk_appetite",
    "earnings",
    "commodity",
    "unknown"
]

SENTIMENT_LABEL_TO_SCORE = {
    "very_positive": 2.0,
    "positive": 1.0,
    "mild_positive": 0.5,
    "neutral": 0.0,
    "mild_negative": -0.5,
    "negative": -1.0,
    "very_negative": -2.0,
    "unknown": 0.0,
}

HORIZONS = [
    "intraday",
    "1d_5d",
    "1w_1m",
    "1m_1q",
    "1q_1y",
    "structural",
    "unknown"
]

TRANSMISSION_LABELS = [
    "risk_on",
    "risk_off",
    "liquidity_easing",
    "liquidity_tightening",
    "growth_upgrade",
    "growth_downgrade",
    "inflation_pressure",
    "disinflation_support",
    "credit_easing",
    "credit_tightening",
    "collateral_improvement",
    "collateral_impairment",
    "fx_pressure",
    "external_relief",
    "counterparty_stress",
    "market_breadth_improvement",
    "market_breadth_deterioration"
]

MOZYFIN_TOPIC_TO_CHANNEL = {
    "economic": "growth",
    "forex": "fx_external",
    "oil": "commodity",
    "tariff": "fx_external",
    "trade": "growth",
    "geopolitical": "risk_appetite",
    "tech": "earnings",
    "earning": "earnings",
    "housing": "real_estate_collateral",
    "mergers_and_ipo": "risk_appetite",
    "crypto": "risk_appetite",
    "stock": "risk_appetite",
}

MOZYFIN_SECTOR_TO_CHANNEL = {
    "banking-35": "banking_system",
    "real-estate-84": "real_estate_collateral",
    "financial-services-143": "liquidity",
    "construction-materials-69": "fiscal_public_investment",
    "steel-metals-12": "growth",
    "oil-gas-157": "commodity",
    "retail-53": "growth",
    "logistics-transport-77": "growth",
}

WIDATA_TAG_TO_CHANNEL = {
    "Tỷ giá": "fx_external",
    "USD/VND": "fx_external",
    "DXY": "fx_external",
    "Ngoại hối": "fx_external",

    "Lãi suất": "monetary_policy",
    "Lãi suất liên ngân hàng": "liquidity",
    "OMO": "liquidity",
    "Tín phiếu": "liquidity",
    "Thanh khoản": "liquidity",

    "Trái phiếu": "credit_stress",
    "Trái phiếu doanh nghiệp": "credit_stress",
    "Nợ xấu": "credit_stress",
    "Tín dụng": "banking_system",

    "Ngân hàng": "banking_system",
    "CASA": "banking_system",
    "NIM": "banking_system",
    "CAR": "banking_system",

    "Bất động sản": "real_estate_collateral",
    "Nhà ở": "real_estate_collateral",
    "Pháp lý dự án": "real_estate_collateral",

    "CPI": "inflation",
    "Lạm phát": "inflation",
    "Giá dầu": "commodity",
    "Hàng hóa": "commodity",

    "GDP": "growth",
    "PMI": "growth",
    "Xuất khẩu": "growth",
    "Bán lẻ": "growth",
    "IIP": "growth",

    "Đầu tư công": "fiscal_public_investment",
    "Ngân sách": "fiscal_public_investment",

    "Chứng khoán": "risk_appetite",
    "VN-Index": "risk_appetite",
    "Khối ngoại": "risk_appetite",
    "Margin": "liquidity",
}

RAW_IMPACT_TO_SCORE = {
    "bullish": 1.0,
    "neutral": 0.0,
    "bearish": -1.0,
    None: 0.0,
}

IMPORTANT_LEVEL_TO_MAGNITUDE = {
    0: 0.5,
    1: 0.75,
    2: 1.0,
    3: 1.5,
    4: 2.0,
    5: 2.0,
}

# Section 7 Keyword rules
LIQUIDITY_KEYWORDS = {
    "sbv_injection": ["bơm ròng", "bơm tiền", "OMO", "mua kỳ hạn"],
    "sbv_withdrawal": ["hút ròng", "tín phiếu", "hút tiền"],
    "interbank_rate_spike": ["lãi suất liên ngân hàng tăng", "qua đêm tăng", "overnight rate spike"],
    "interbank_rate_decline": ["lãi suất liên ngân hàng giảm", "qua đêm giảm"],
    "deposit_rate_increase": ["lãi suất huy động tăng"],
    "deposit_rate_decline": ["lãi suất huy động giảm"],
    "margin_call_pressure": ["call margin", "force sell", "bán giải chấp"],
}

FX_KEYWORDS = {
    "vnd_depreciation": ["VND giảm", "tỷ giá tăng", "USD/VND tăng", "mất giá"],
    "vnd_stabilization": ["tỷ giá ổn định", "VND ổn định"],
    "dxy_rise": ["DXY tăng", "đồng USD mạnh"],
    "dxy_fall": ["DXY giảm", "đồng USD yếu"],
    "fed_hawkish": ["Fed hawkish", "Fed tăng lãi suất", "lãi suất cao lâu hơn"],
    "fed_dovish": ["Fed dovish", "Fed cắt giảm lãi suất", "nới lỏng"],
    "foreign_outflow": ["khối ngoại bán ròng", "rút vốn"],
    "foreign_inflow": ["khối ngoại mua ròng", "dòng vốn ngoại vào"],
}

CREDIT_STRESS_KEYWORDS = {
    "npl_increase": ["nợ xấu tăng", "NPL tăng", "nợ nhóm 2 tăng"],
    "bond_default": ["chậm trả", "vỡ nợ", "không thanh toán", "default"],
    "bond_restructuring": ["gia hạn trái phiếu", "tái cấu trúc nợ"],
    "credit_downgrade": ["hạ xếp hạng", "downgrade"],
    "counterparty_stress": ["căng thẳng liên ngân hàng", "thiếu thanh khoản", "đứt gãy thanh khoản"],
}

REAL_ESTATE_KEYWORDS = {
    "legal_easing": ["tháo gỡ pháp lý", "gỡ vướng dự án", "phê duyệt dự án"],
    "presales_recovery": ["mở bán thành công", "presales tăng", "doanh số bán hàng phục hồi"],
    "inventory_pressure": ["tồn kho tăng", "hàng tồn kho bất động sản"],
    "developer_default": ["chủ đầu tư chậm trả", "developer default", "trái phiếu bất động sản chậm trả"],
    "property_price_decline": ["giá nhà giảm", "giá đất giảm", "cắt lỗ"],
    "mortgage_easing": ["nới tín dụng bất động sản", "lãi vay mua nhà giảm"],
}

BANKING_KEYWORDS = {
    "nim_expansion": ["NIM tăng", "biên lãi ròng cải thiện"],
    "nim_compression": ["NIM giảm", "biên lãi ròng thu hẹp"],
    "casa_recovery": ["CASA tăng", "tiền gửi không kỳ hạn tăng"],
    "npl_pressure": ["nợ xấu", "NPL", "trích lập tăng"],
    "car_improvement": ["CAR tăng", "tăng vốn", "an toàn vốn"],
    "funding_stress": ["áp lực huy động", "thiếu thanh khoản", "LDR cao"],
}

# Transmission rule mapping
EVENT_TRANSMISSION = {
    "sbv_injection": ["liquidity_easing", "risk_on"],
    "sbv_withdrawal": ["liquidity_tightening", "risk_off"],
    "interbank_rate_spike": ["liquidity_tightening", "counterparty_stress", "risk_off"],
    "interbank_rate_decline": ["liquidity_easing", "risk_on"],
    "deposit_rate_increase": ["liquidity_tightening"],
    "deposit_rate_decline": ["liquidity_easing"],
    "margin_call_pressure": ["risk_off", "liquidity_tightening"],
    
    "vnd_depreciation": ["fx_pressure", "risk_off"],
    "vnd_stabilization": ["external_relief", "risk_on"],
    "dxy_rise": ["fx_pressure"],
    "dxy_fall": ["external_relief"],
    "fed_hawkish": ["fx_pressure", "risk_off"],
    "fed_dovish": ["external_relief", "risk_on"],
    "foreign_outflow": ["fx_pressure", "risk_off"],
    "foreign_inflow": ["external_relief", "risk_on"],
    
    "npl_increase": ["credit_tightening", "collateral_impairment", "risk_off"],
    "bond_default": ["counterparty_stress", "credit_tightening", "risk_off"],
    "bond_restructuring": ["counterparty_stress", "credit_easing"],
    "credit_downgrade": ["counterparty_stress", "risk_off"],
    "counterparty_stress": ["counterparty_stress", "liquidity_tightening", "risk_off"],
    
    "legal_easing": ["collateral_improvement", "credit_easing", "risk_on"],
    "presales_recovery": ["collateral_improvement", "growth_upgrade"],
    "inventory_pressure": ["collateral_impairment", "growth_downgrade"],
    "developer_default": ["collateral_impairment", "credit_tightening", "risk_off"],
    "property_price_decline": ["collateral_impairment", "risk_off"],
    "mortgage_easing": ["credit_easing", "collateral_improvement"],
    
    "nim_expansion": ["growth_upgrade"],
    "nim_compression": ["growth_downgrade"],
    "casa_recovery": ["liquidity_easing"],
    "npl_pressure": ["credit_tightening", "risk_off"],
    "car_improvement": ["credit_easing"],
    "funding_stress": ["liquidity_tightening", "counterparty_stress"]
}

EVENT_HORIZON = {
    # Default horizons per event
    "sbv_injection": "1d_5d",
    "sbv_withdrawal": "1d_5d",
    "interbank_rate_spike": "1d_5d",
    "interbank_rate_decline": "1d_5d",
    "deposit_rate_increase": "1w_1m",
    "deposit_rate_decline": "1w_1m",
    "margin_call_pressure": "1d_5d",
    
    "vnd_depreciation": "1w_1m",
    "vnd_stabilization": "1w_1m",
    "dxy_rise": "1w_1m",
    "dxy_fall": "1w_1m",
    "fed_hawkish": "1m_1q",
    "fed_dovish": "1m_1q",
    "foreign_outflow": "1d_5d",
    "foreign_inflow": "1d_5d",
    
    "npl_increase": "1m_1q",
    "bond_default": "1m_1q",
    "bond_restructuring": "1m_1q",
    "credit_downgrade": "1w_1m",
    "counterparty_stress": "1d_5d",
    
    "legal_easing": "1q_1y",
    "presales_recovery": "1m_1q",
    "inventory_pressure": "1m_1q",
    "developer_default": "1m_1q",
    "property_price_decline": "1m_1q",
    "mortgage_easing": "1m_1q",
    
    "nim_expansion": "1m_1q",
    "nim_compression": "1m_1q",
    "casa_recovery": "1m_1q",
    "npl_pressure": "1m_1q",
    "car_improvement": "1q_1y",
    "funding_stress": "1w_1m"
}
