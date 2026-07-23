from __future__ import annotations

import importlib.util
from pathlib import Path

from command.generate_report import discover_report_tools
from shared.tool_registry import TOOL_REGISTRY, get_tool, report_tool_ids, tools_for_branch


ROOT = Path(__file__).resolve().parents[1]


def test_tool_registry_ids_are_unique() -> None:
    ids = [tool.id for tool in TOOL_REGISTRY]

    assert len(ids) == len(set(ids))


def test_branch_catalog_order_matches_app_hubs() -> None:
    assert [tool["id"] for tool in tools_for_branch("macro")] == [
        "fed_liquidity",
        "global_financial_conditions",
        "humility_falsification",
        "vnibor",
        "bank_valuation",
        "ltmm",
        "vn100_earnings_health",
        "credit_spread",
    ]
    assert [tool["id"] for tool in tools_for_branch("micro")] == [
        "pairs_trading",
        "factor_examination",
        "risk_adjusted_growth",
    ]
    assert [tool["id"] for tool in tools_for_branch("behavioral")] == [
        "fear_greed",
        "sentiment_factor_news",
        "pvgo",
        "upside_ratio",
        "market_breadth",
        "esr_monitor",
        "dispersion",
        "va_res",
        "manipulation",
        "var_cvar_vnindex",
        "abm_simulator",
    ]
    assert get_tool("backtest").catalog_visible is False


def test_registered_page_modules_are_resolvable() -> None:
    for tool in TOOL_REGISTRY:
        if tool.page_module is None:
            continue
        assert importlib.util.find_spec(tool.page_module) is not None, tool.id


def test_report_flags_match_tool_report_files() -> None:
    for tool in TOOL_REGISTRY:
        if tool.package is None or not tool.package.startswith("tools."):
            continue
        package_path = ROOT.joinpath(*tool.package.split("."))
        if not package_path.exists():
            continue
        assert tool.has_report == (package_path / "report.py").exists(), tool.id


def test_generate_report_uses_registry_report_order() -> None:
    expected = [
        tool_id
        for tool_id in report_tool_ids()
        if (ROOT / "tools" / tool_id / "report.py").exists()
    ]

    assert discover_report_tools(ROOT) == expected
