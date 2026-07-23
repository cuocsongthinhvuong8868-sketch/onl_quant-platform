from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BranchId = Literal["macro", "micro", "behavioral", "data", "engine"]


@dataclass(frozen=True)
class BranchDefinition:
    id: BranchId
    name: str
    page: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    branch: BranchId
    name: str
    desc: str
    page_module: str | None = None
    render_func: str = "render"
    package: str | None = None
    page_entry: str | None = None
    has_report: bool = False
    update_commands: tuple[str, ...] = ()
    cache_namespaces: tuple[str, ...] = ()
    ai_cio_role: str = "none"
    catalog_visible: bool = True
    status: str = "active"

    def to_page_dict(self) -> dict[str, str]:
        if self.page_module is None:
            raise ValueError(f"{self.id} does not define a Streamlit page module")
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "page_module": self.page_module,
            "render_func": self.render_func,
        }

    @property
    def report_module(self) -> str | None:
        if not self.has_report or self.package is None:
            return None
        return f"{self.package}.report"


BRANCHES: dict[BranchId, BranchDefinition] = {
    "macro": BranchDefinition("macro", "Macro Analysis", "pages/A_Macro_Analysis.py"),
    "micro": BranchDefinition("micro", "Micro Analysis", "pages/B_Micro_Analysis.py"),
    "behavioral": BranchDefinition(
        "behavioral",
        "Behavioral Finance",
        "pages/C_Behavioral_Finance.py",
    ),
    "data": BranchDefinition("data", "Data Health", "pages/D_Data_Health.py"),
    "engine": BranchDefinition("engine", "Engine / Evidence Gates"),
}


TOOL_REGISTRY: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        id="fed_liquidity",
        branch="macro",
        name="🏦 Fed Liquidity Monitor",
        desc="Net Liquidity (WALCL − TGA − RRP) + Impulse EMA + Z-Score 52W → Tín hiệu ADD/CUT/HOLD",
        page_module="tools.fed_liquidity.page",
        package="tools.fed_liquidity",
        page_entry="pages/tools_page_A/_1_Fed_Liquidity.py",
        has_report=True,
        update_commands=("python command/update_fed_liquidity.py",),
        cache_namespaces=("fed_liquidity",),
        ai_cio_role="macro_child_report",
    ),
    ToolDefinition(
        id="global_financial_conditions",
        branch="macro",
        name="🌐 Global Financial Conditions",
        desc="VIX + MOVE + HY OAS + CCC OAS · Static PCA composite · Regime via PC1 percentile rank 3Y (STRESS/ELEVATED/CALM)",
        page_module="tools.global_financial_conditions.page",
        package="tools.global_financial_conditions",
        page_entry="pages/tools_page_A/_2_Global_Financial_Conditions.py",
        has_report=True,
        update_commands=("python command/update_global_financial_conditions.py",),
        cache_namespaces=("global_financial_conditions",),
        ai_cio_role="macro_child_report",
    ),
    ToolDefinition(
        id="humility_falsification",
        branch="macro",
        name="🧭 Humility & Falsification Monitor",
        desc="Đối chiếu điều kiện falsification trong AI CIO T-1 với dữ liệu T từ VNIBOR, Breadth, ESR, EVT, Coupling và Global Conditions",
        page_module="tools.humility_falsification.page",
        package="tools.humility_falsification",
        page_entry="pages/tools_page_A/_5_Humility_Falsification.py",
        cache_namespaces=("humility_falsification",),
        ai_cio_role="audit_evidence",
    ),
    ToolDefinition(
        id="vnibor",
        branch="macro",
        name="🏦 VNIBOR Monitor",
        desc="Lãi suất qua đêm và các kỳ hạn ngắn liên ngân hàng · Phân loại trạng thái thanh khoản (Regime Percentile 1Y) · Tác động tới VN-Index",
        page_module="tools.vnibor.page",
        package="tools.vnibor",
        page_entry="pages/tools_page_A/_3_VietNam_VNIBOR.py",
        has_report=True,
        update_commands=("python -m command.update_vnibor",),
        cache_namespaces=("vnibor",),
        ai_cio_role="macro_child_report",
    ),
    ToolDefinition(
        id="bank_valuation",
        branch="macro",
        name="🏦 Bank Valuation",
        desc="Định giá bottom-up nhóm ngân hàng: Adjusted Book Value, Sustainable ROE, Residual Income, stress fair P/B và regime từ valuation breadth.",
        page_module="tools.bank_valuation.page",
        package="tools.bank_valuation",
        page_entry="pages/tools_page_A/_6_Bank_Valuation.py",
        has_report=True,
        update_commands=("python command/update_bank_valuation_data.py",),
        cache_namespaces=("bank_valuation", "bank_valuation_ai"),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="ltmm",
        branch="macro",
        name="📊 Liquidity Transmission (LTMM)",
        desc="Theo dõi kênh truyền dẫn thanh khoản hệ thống: Thượng nguồn (upstream), Lớp ma sát (friction), và Hạ nguồn (market liquidity)",
        page_module="tools.ltmm.page",
        package="tools.ltmm",
        page_entry="pages/tools_page_A/_4_LTMM.py",
        ai_cio_role="macro_context",
    ),
    ToolDefinition(
        id="vn100_earnings_health",
        branch="macro",
        name="🇻🇳 VN100 Corporate Health",
        desc="Bottom-up VN100 financial statement monitor: growth quality, cash conversion, working-capital stress, leverage stress, sector diffusion và matrix diagnostics",
        page_module="tools.vn100_earnings_health.page",
        package="tools.vn100_earnings_health",
        page_entry="pages/tools_page_A/_3_VN100_Earnings_Health.py",
        update_commands=("python -m command.update_vn100_corporate_health",),
        cache_namespaces=("vn100_earnings_health",),
        ai_cio_role="macro_context",
    ),
    ToolDefinition(
        id="credit_spread",
        branch="macro",
        name="💳 Credit Spread Bank vs BĐS",
        desc="So sánh lãi suất phát hành trái phiếu Bank và BĐS, spread theo kỳ, kỳ hạn và phần bù so với TPCP Việt Nam",
        page_module="tools.credit_spread.page",
        package="tools.credit_spread",
        update_commands=("python command/update_credit_spread_data.py",),
        cache_namespaces=("credit_spread",),
        ai_cio_role="macro_child_report",
    ),
    ToolDefinition(
        id="pairs_trading",
        branch="micro",
        name="🔁 Pairs Trading Research Lab",
        desc=(
            "Cointegration (Engle-Granger + Johansen) + OU half-life + Z-score 60d trên 7 cluster VN "
            "(Vingroup, Big4 Bank, Steel, Securities, Private Bank, Oil&Gas, Utility) + custom pair UI."
        ),
        page_module="tools.pairs_trading.page",
        package="tools.pairs_trading",
        page_entry="pages/tools_page_B/_1_Pairs_Trading.py",
        ai_cio_role="research_tool",
    ),
    ToolDefinition(
        id="factor_examination",
        branch="micro",
        name="📐 Portfolio Factor Examination",
        desc=(
            "Multi-factor cross-sectional scorer (10 factor price-based, sector-neutral ICB): "
            "Mom/LowVol/Beta/IdioVol/Liquidity/Size/Anti-Lottery/Reversal. Portfolio examination — "
            "xếp hạng tickers ổn hơn phần còn lại. KHÔNG phải regime classifier."
        ),
        page_module="tools.factor_examination.page",
        package="tools.factor_examination",
        update_commands=("python -m command.update_factor_examination",),
        cache_namespaces=("factor_examination", "factor_examination_ic"),
        ai_cio_role="standalone_ai",
    ),
    ToolDefinition(
        id="risk_adjusted_growth",
        branch="micro",
        name="📊 Risk-Adjusted Growth",
        desc="Phân tích tăng trưởng điều chỉnh rủi ro — Economic Alpha, P/B, ROE và Cash Payout cho nhóm ngân hàng.",
        page_module="tools.risk_adjusted_growth.page",
        package="tools.risk_adjusted_growth",
        page_entry="pages/tools_page_B/_3_Risk_Adjusted_Growth.py",
        has_report=True,
        update_commands=("python command/update_risk_adjusted_growth_statistics.py",),
        cache_namespaces=("risk_adjusted_growth",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="fear_greed",
        branch="behavioral",
        name="🎯 Market Sentiment (Fear & Greed)",
        desc="PCA & EGARCH — Đo lường tâm lý thị trường qua PCA, EGARCH(1,1,1) Skewed-T, Kelly Skewness",
        page_module="tools.fear_greed.page",
        package="tools.fear_greed",
        page_entry="pages/tools_page_C/_1_Fear_Greed.py",
        has_report=True,
        cache_namespaces=("fear_greed", "feargreed"),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="sentiment_factor_news",
        branch="behavioral",
        name="📰 News Sentiment Factor",
        desc="Rule-based macro/news sentiment feed từ Mozyfin và WiData: composite, regime, channel scores và headline drivers.",
        page_module="tools.sentiment_factor_news.page",
        package="tools.sentiment_factor_news",
        page_entry="pages/tools_page_C/_10_Sentiment_Factor_News.py",
        has_report=True,
        update_commands=("python command/update_sentiment_factor_news.py --once",),
        cache_namespaces=("sentiment_factor_news",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="pvgo",
        branch="behavioral",
        name="PVGO Valuation Model",
        desc="Present Value of Growth Opportunities cho VN-Index: P/E, COE, steady-state value và growth expectations.",
        page_module="tools.pvgo.page",
        package="tools.pvgo",
        page_entry="pages/tools_page_C/_11_PVGO_Valuation.py",
        has_report=True,
        update_commands=("python -m command.update_pvgo_valuation",),
        cache_namespaces=("pvgo",),
        ai_cio_role="valuation_context",
    ),
    ToolDefinition(
        id="upside_ratio",
        branch="behavioral",
        name="🧬 Upside/Downside Ratio",
        desc="Hybrid MC Bidirectional Breadth Model — Phân tích Cung-Cầu với Monte Carlo ensemble",
        page_module="tools.upside_ratio.page",
        package="tools.upside_ratio",
        page_entry="pages/tools_page_C/_2_Upside_Ratio.py",
        has_report=True,
        cache_namespaces=("upside_ratio",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="market_breadth",
        branch="behavioral",
        name="📈 Market Breadth",
        desc="Độ rộng thị trường — Số mã >MA20/60/125/252, Top 10 Volume Leaders",
        page_module="tools.market_breadth.page",
        package="tools.market_breadth",
        page_entry="pages/tools_page_C/_4_Market_Breadth.py",
        has_report=True,
        cache_namespaces=("market_breadth",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="esr_monitor",
        branch="behavioral",
        name="⚡ ESR Monitor",
        desc="Hệ thống Cảnh báo Rủi ro Hệ thống — PCA trên VN30, phát hiện SAFE/WARNING/CRITICAL",
        page_module="tools.esr_monitor.page",
        package="tools.esr_monitor",
        page_entry="pages/tools_page_C/_5_ESR_Monitor.py",
        has_report=True,
        cache_namespaces=("esr_monitor",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="dispersion",
        branch="behavioral",
        name="🔄 Dispersion",
        desc="Phân tích phân tán thị trường — Volatility skew, term structure",
        page_module="tools.dispersion.page",
        package="tools.dispersion",
        page_entry="pages/tools_page_C/_6_Dispersion.py",
        has_report=True,
        cache_namespaces=("dispersion",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="va_res",
        branch="behavioral",
        name="🛡️ VaRES Engine",
        desc="3 Module: A-Single Ticker, B-VN30 Stress, C-Market Complacency với Self-Baseline",
        page_module="tools.va_res.page",
        render_func="show",
        package="tools.va_res",
        page_entry="pages/tools_page_C/_7_VaRES_Engine.py",
        has_report=True,
        cache_namespaces=("va_res",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="manipulation",
        branch="behavioral",
        name="🔍 Manipulation Detection",
        desc="Phát hiện dấu hiệu thao túng giá — Các metrics đặc biệt về hành vi giao dịch",
        page_module="tools.manipulation.page",
        package="tools.manipulation",
        page_entry="pages/tools_page_C/_8_Manipulation.py",
        has_report=True,
        cache_namespaces=("manipulation",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="var_cvar_vnindex",
        branch="behavioral",
        name="📉 Var-CVaR VNINDEX",
        desc="Value-at-Risk & Expected Shortfall cho VNINDEX — Rolling σ, Parametric & Historical VaR, ES",
        page_module="tools.var_cvar_vnindex.page",
        render_func="show",
        package="tools.var_cvar_vnindex",
        page_entry="pages/tools_page_C/_9_Var_CVaR_VNINDEX.py",
        has_report=True,
        cache_namespaces=("var_cvar_vnindex",),
        ai_cio_role="executive_scoring",
    ),
    ToolDefinition(
        id="abm_simulator",
        branch="behavioral",
        name="ABM Market Simulator",
        desc="Agent-based monitor for leverage stress, panic ratio, forced-selling amplification and margin cascade distance.",
        page_module="tools.abm_simulator.page",
        package="tools.abm_simulator",
        page_entry="pages/tools_page_C/_12_ABM_Simulator.py",
        update_commands=("python -m command.update_abm_data",),
        cache_namespaces=("abm_simulator",),
        ai_cio_role="structured_context",
    ),
    ToolDefinition(
        id="backtest",
        branch="behavioral",
        name="⚖️ Backtest Strategy",
        desc="Composite risk signal, allocation overlay và strategy diagnostics.",
        page_module="tools.backtest.page",
        render_func="show",
        package="tools.backtest",
        ai_cio_role="research_tool",
        catalog_visible=False,
    ),
    ToolDefinition(
        id="data_health",
        branch="data",
        name="Data Health",
        desc="Freshness, missing-date timeline, JSON/CSV health report.",
        page_module="pages.D_Data_Health",
        package="pages",
        page_entry="pages/D_Data_Health.py",
        update_commands=("python command/data_health_report.py",),
        ai_cio_role="operations",
    ),
    ToolDefinition(
        id="capitulation_regime",
        branch="engine",
        name="Capitulation Regime",
        desc="Deterministic price-path capitulation phase gate for AI CIO evidence.",
        package="tools.capitulation_regime",
        ai_cio_role="diagnostic_gate",
        catalog_visible=False,
    ),
)


def iter_tools(
    branch: BranchId | None = None,
    *,
    include_hidden: bool = True,
) -> tuple[ToolDefinition, ...]:
    tools = TOOL_REGISTRY
    if branch is not None:
        tools = tuple(tool for tool in tools if tool.branch == branch)
    if not include_hidden:
        tools = tuple(tool for tool in tools if tool.catalog_visible)
    return tools


def get_tool(tool_id: str) -> ToolDefinition:
    for tool in TOOL_REGISTRY:
        if tool.id == tool_id:
            return tool
    raise KeyError(f"Unknown tool id: {tool_id}")


def tools_for_branch(
    branch: BranchId,
    *,
    include_hidden: bool = False,
) -> list[dict[str, str]]:
    return [
        tool.to_page_dict()
        for tool in iter_tools(branch, include_hidden=include_hidden)
        if tool.page_module is not None
    ]


def report_tool_ids() -> list[str]:
    return [tool.id for tool in TOOL_REGISTRY if tool.has_report]


def registry_by_id() -> dict[str, ToolDefinition]:
    return {tool.id: tool for tool in TOOL_REGISTRY}
