from tools.bank_valuation.quant.engine.schema import ValuationOutput


def _fmt_number(value: float, digits: int = 2) -> str:
    try:
        if value != value:
            return "N/A"
        return f"{value:.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(value: float) -> str:
    try:
        if value != value:
            return "N/A"
        return f"{value * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def generate_markdown_report(output: ValuationOutput) -> str:
    md = f"# Valuation Report: {output.ticker}\n\n"
    md += f"**Period:** {output.period}\n"
    md += f"**Classification:** {output.classification}\n"
    md += f"**Data Quality:** {output.data_quality_flag}\n"
    md += f"**Valuation Gap:** {_fmt_pct(output.valuation_gap_pct)}\n\n"
    
    md += "## Executive Summary\n"
    md += f"- **Current Price:** {output.price}\n"
    md += f"- **Fair Value (RIM):** {_fmt_number(output.fair_value_per_share_rim)}\n"
    md += f"- **Fair Value (P/B):** {_fmt_number(output.fair_value_per_share_pb)}\n"
    md += f"- **Stress Downside:** {_fmt_number(output.stress_value_per_share)}\n\n"
    
    md += "## Valuation Snapshot\n"
    md += f"- **Reported BVPS:** {_fmt_number(output.book_value_per_share)}\n"
    md += f"- **Adjusted BVPS:** {_fmt_number(output.adjusted_book_value_per_share)}\n"
    md += f"- **Market P/B:** {_fmt_number(output.market_pb)}x\n"
    md += f"- **Justified P/B:** {_fmt_number(output.justified_pb)}x\n\n"

    md += "## Relative Value Check\n"
    md += f"- **Peer Median P/B:** {_fmt_number(output.peer_median_pb)}x\n"
    md += f"- **Peer Median ROE:** {_fmt_pct(output.peer_median_roe)}\n"
    md += f"- **ROE-Adjusted Fair P/B:** {_fmt_number(output.roe_adjusted_fair_pb)}x\n"
    md += f"- **Market Mispricing Score:** {_fmt_pct(output.market_mispricing_score)}\n"
    md += f"- **Relative Valuation Label:** {output.relative_valuation_label}\n"
    if output.relative_value_warning:
        md += f"- **Relative Value Warning:** {output.relative_value_warning}\n"
    md += "\n"
    
    md += "## Profitability & Cost of Equity\n"
    md += f"- **Reported ROE:** {_fmt_pct(output.reported_roe)}\n"
    md += f"- **Sustainable ROE:** {_fmt_pct(output.sustainable_roe)}\n"
    md += f"- **Cost of Equity:** {_fmt_pct(output.cost_of_equity)}\n\n"
    
    md += "## Risk Scores (0-100, Lower is Better)\n"
    md += f"- **Credit Cycle Risk:** {output.credit_cycle_score:.1f}\n"
    md += f"- **Collateral Risk:** {output.collateral_risk_score:.1f}\n"
    md += f"- **Funding Quality Risk:** {100 - output.funding_quality_score:.1f} (Raw Score: {output.funding_quality_score:.1f})\n"
    md += f"- **Capital Dilution Risk:** {output.capital_dilution_risk_score:.1f}\n"
    md += f"- **Overall Risk Score:** {output.overall_risk_score:.1f}\n\n"
    
    md += "## Warnings\n"
    if output.warnings:
        for w in output.warnings:
            md += f"- {w}\n"
    else:
        md += "- None\n"
        
    return md
