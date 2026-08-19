from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from shared.llm_policy import completion_options
from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime


AI_PROVIDER_MAP = {
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
        "api_model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "temperature": 0.5,
    },
    "kimi-2.6": {
        "display": "Kimi 2.6",
        "api_model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
        "temperature": 1.0,
    },
    "kimi-2.6-local": {
        "display": "Kimi 2.6 Local",
        "api_model": "kimi-k2.6",
        "base_url": "http://127.0.0.1:5001/v1",
        "temperature": 0.4,
    },
    "chatgpt-local": {
        "display": "ChatGPT Local",
        "api_model": "gpt-5.5",
        "base_url": "http://127.0.0.1:5003/v1",
        "temperature": 0.2,
    },
}


def get_ai_cache_file(output_folder: str | Path, provider_key: str, run_date: date | None = None) -> Path:
    run_date = run_date or date.today()
    date_str = run_date.strftime("%d%m%y")
    return Path(output_folder) / "ai_analysis" / f"bank_valuation_ai_{provider_key}_{date_str}.txt"


def list_ai_cache_files(output_folder: str | Path) -> list[Path]:
    cache_dir = Path(output_folder) / "ai_analysis"
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.glob("bank_valuation_ai_*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)


def _format_pct(value: object) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):+.1%}"


def _format_num(value: object, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def _existing_columns(data: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    return [col for col in columns if col in data.columns]


def _compact_table(data: pd.DataFrame, columns: Iterable[str], limit: int = 25) -> str:
    cols = _existing_columns(data, columns)
    if not cols or data.empty:
        return "No rows."

    table = data.loc[:, cols].head(limit).copy()
    for col in table.select_dtypes(include="number").columns:
        table[col] = table[col].round(4)
    return table.to_csv(index=False)


def _count_classifications(data: pd.DataFrame) -> dict[str, int]:
    if "classification" not in data.columns:
        return {"overvalued": 0, "fair": 0, "undervalued": 0, "other": len(data)}

    labels = data["classification"].fillna("")
    return {
        "overvalued": int((labels == "Overvalued").sum()),
        "fair": int((labels == "Fairly Valued").sum()),
        "undervalued": int(labels.isin(["Strong Undervalued", "Undervalued but Risky"]).sum()),
        "other": int((~labels.isin(["Overvalued", "Fairly Valued", "Strong Undervalued", "Undervalued but Risky"])).sum()),
    }


def _top_line(data: pd.DataFrame, column: str, ascending: bool, label: str) -> str:
    if column not in data.columns:
        return f"{label}: N/A"

    ranked = data.dropna(subset=[column]).sort_values(column, ascending=ascending).head(5)
    if ranked.empty:
        return f"{label}: N/A"

    parts = []
    for _, row in ranked.iterrows():
        ticker = row.get("ticker", "N/A")
        value = row[column]
        if "pct" in column or column in {"sustainable_roe", "cost_of_equity", "return_20d", "return_60d", "drawdown_60d"}:
            value_text = _format_pct(value)
        else:
            value_text = _format_num(value)
        parts.append(f"{ticker} ({value_text})")
    return f"{label}: " + ", ".join(parts)


def _regime_context(data: pd.DataFrame) -> str:
    regime = calculate_bank_valuation_regime(data)
    if regime.eligible_banks == 0:
        return "ChÆ°a Ä‘á»§ dá»¯ liá»‡u há»£p lá»‡ Ä‘á»ƒ phÃ¢n loáº¡i tráº¡ng thÃ¡i thá»‹ trÆ°á»ng theo Ä‘á»‹nh giÃ¡ nhÃ³m ngÃ¢n hÃ ng."

    return f"""
PhÃ¢n loáº¡i regime: {regime.regime_label}
MÃ£ há»£p lá»‡: {regime.eligible_banks}
Äá»‹nh giÃ¡ cao: {regime.overvalued_count} ({_format_pct(regime.overvalued_breadth)})
Há»£p lÃ½: {regime.fair_count} ({_format_pct(regime.fair_breadth)})
Ráº» rÃµ rá»‡t: {regime.strong_undervalued_count}
Ráº» nhÆ°ng rá»§i ro: {regime.risky_undervalued_count}
Äiá»ƒm Ä‘á»™ rá»™ng Ä‘á»‹nh giÃ¡: {_format_pct(regime.bank_valuation_breadth_score)}
Gap trung vá»‹: {_format_pct(regime.median_valuation_gap)}
Gap trimmed mean: {_format_pct(regime.trimmed_mean_valuation_gap)}
Gap theo vá»‘n hÃ³a: {_format_pct(regime.market_cap_weighted_gap)}
Gap theo cháº¥t lÆ°á»£ng dá»¯ liá»‡u: {_format_pct(regime.confidence_weighted_gap)}
Äiá»ƒm Ä‘á»‹nh giÃ¡ tÆ°Æ¡ng Ä‘á»‘i theo peer labels: {_format_pct(regime.relative_value_breadth_score)}

PhÆ°Æ¡ng phÃ¡p: {regime.methodology_note}
CÃ´ng thá»©c Ä‘iá»ƒm Ä‘á»™ rá»™ng: (Ráº» rÃµ rá»‡t + 0.5 x Ráº» nhÆ°ng rá»§i ro - Äá»‹nh giÃ¡ cao) / sá»‘ mÃ£ há»£p lá»‡.
NgÆ°á»¡ng Ä‘á»c regime: >= +25% lÃ  Ráº» trÃªn diá»‡n rá»™ng; 0% Ä‘áº¿n +25% lÃ  TÆ°Æ¡ng Ä‘á»‘i ráº»; -25% Ä‘áº¿n 0% lÃ  Trung tÃ­nh; -50% Ä‘áº¿n -25% lÃ  Äá»‹nh giÃ¡ cao, cáº§n chá»n lá»c; dÆ°á»›i -50% lÃ  Äá»‹nh giÃ¡ cao trÃªn diá»‡n rá»™ng.
"""


def build_bank_valuation_ai_prompt(
    data: pd.DataFrame,
    ohlcv_source: str = "none",
    focus_question: str = "",
    report_date: date | None = None,
) -> tuple[str, str]:
    report_date = report_date or date.today()
    report_date_text = report_date.strftime("%d/%m/%Y")
    counts = _count_classifications(data)
    watchlist = data
    if "classification" in data.columns:
        watchlist = data[
            data["classification"].isin(["Fairly Valued", "Strong Undervalued", "Undervalued but Risky"])
        ].copy()

    confirmation_labels = {}
    if "market_confirmation_label" in watchlist.columns:
        confirmation_labels = watchlist["market_confirmation_label"].fillna("No Market Data").value_counts().to_dict()

    warnings_text = "No warning column."
    if "warnings" in data.columns:
        has_warning = ~data["warnings"].fillna("").astype(str).str.strip().isin(["", "[]"])
        warning_rows = data[has_warning]
        warnings_text = _compact_table(warning_rows, ["ticker", "warnings", "confidence_score"], limit=12)

    system_prompt = (
        "You are a senior Vietnam bank equity analyst and market-regime analyst. "
        "Use only the supplied valuation and market-confirmation data. "
        "Do not invent missing financial data. "
        "Classify market regime only from the supplied bank-valuation breadth methodology, "
        "not from macro narratives, index technicals, liquidity flows, or headline market P/E. "
        "Clearly separate model valuation signals from market price confirmation. "
        "Answer in Vietnamese, concise but decision-useful."
    )

    user_prompt = f"""
# INPUT DATA

## Universe
- NgÃ y bÃ¡o cÃ¡o AI: {report_date_text}
- Tickers: {len(data)}
- Overvalued: {counts["overvalued"]}
- Fair value: {counts["fair"]}
- Undervalued: {counts["undervalued"]}
- Other / need more data: {counts["other"]}
- OHLCV source: {ohlcv_source}

## Tráº¡ng thÃ¡i thá»‹ trÆ°á»ng hÃ m Ã½ tá»« Ä‘á»‹nh giÃ¡ nhÃ³m ngÃ¢n hÃ ng
{_regime_context(data)}

## Market confirmation labels for fair + undervalued watchlist
{confirmation_labels if confirmation_labels else "No market confirmation labels available."}

## Ranking signals
{_top_line(data, "valuation_gap_pct", False, "Highest valuation gap")}
{_top_line(data, "valuation_gap_pct", True, "Lowest valuation gap")}
{_top_line(data, "overall_risk_score", True, "Lowest risk score")}
{_top_line(data, "overall_risk_score", False, "Highest risk score")}
{_top_line(data, "market_confirmation_score", False, "Strongest market confirmation")}
{_top_line(data, "market_confirmation_score", True, "Weakest market confirmation")}

## Focus question
{focus_question.strip() or "Give a complete bank-valuation data review."}

## Watchlist table
{_compact_table(
        watchlist.sort_values("valuation_gap_pct", ascending=False) if "valuation_gap_pct" in watchlist.columns else watchlist,
        [
            "ticker",
            "classification",
            "price",
            "fair_value_per_share_rim",
            "valuation_gap_pct",
            "overall_risk_score",
            "confidence_score",
            "data_quality_flag",
            "beta",
            "relative_valuation_label",
            "market_mispricing_score",
            "roe_adjusted_fair_pb",
            "market_confirmation_score",
            "market_confirmation_label",
            "return_20d",
            "return_60d",
            "volume_ratio_20d",
            "drawdown_60d",
        ],
        limit=25,
    )}

## Full universe valuation table
{_compact_table(
        data.sort_values("valuation_gap_pct", ascending=False) if "valuation_gap_pct" in data.columns else data,
        [
            "ticker",
            "classification",
            "price",
            "fair_value_per_share_rim",
            "stress_value_per_share",
            "valuation_gap_pct",
            "market_pb",
            "justified_pb",
            "peer_median_pb",
            "roe_adjusted_fair_pb",
            "market_mispricing_score",
            "relative_valuation_label",
            "sustainable_roe",
            "cost_of_equity",
            "overall_risk_score",
            "credit_cycle_score",
            "funding_quality_score",
            "collateral_risk_score",
            "capital_dilution_risk_score",
            "car",
            "npl_ratio",
            "provision_coverage",
            "data_quality_flag",
            "confidence_score",
            "warnings",
        ],
        limit=35,
    )}

## Rows with data warnings
{warnings_text}

# REQUIRED OUTPUT
1. DÃ²ng má»Ÿ Ä‘áº§u: ghi rÃµ "NgÃ y bÃ¡o cÃ¡o AI: {report_date_text}".
2. PhÃ¢n loáº¡i regime: nÃªu rÃµ nhÃ£n "Tráº¡ng thÃ¡i thá»‹ trÆ°á»ng hÃ m Ã½ tá»« Ä‘á»‹nh giÃ¡ nhÃ³m ngÃ¢n hÃ ng", Ä‘iá»ƒm Ä‘á»™ rá»™ng, sá»‘ mÃ£ Ä‘á»‹nh giÃ¡ cao / há»£p lÃ½ / ráº», vÃ  káº¿t luáº­n biÃªn an toÃ n hiá»‡n táº¡i.
3. Luáº­n Ä‘iá»ƒm chÃ­nh: 3-5 bullets giáº£i thÃ­ch vÃ¬ sao regime Ä‘Ã³ Ä‘Æ°á»£c suy ra tá»« valuation breadth cá»§a nhÃ³m ngÃ¢n hÃ ng.
4. Kiá»ƒm tra chÃ©o: Ä‘á»‹nh giÃ¡ tÆ°Æ¡ng Ä‘á»‘i vÃ  xÃ¡c nháº­n giÃ¡ Ä‘ang cá»§ng cá»‘ hay phá»§ Ä‘á»‹nh káº¿t luáº­n regime.
5. TÃ­n hiá»‡u theo mÃ£: mÃ£ nÃ o Ä‘Ã¡ng theo dÃµi trong nhÃ³m há»£p lÃ½/ráº», mÃ£ nÃ o lÃ  rá»§i ro hoáº·c Ä‘ang bá»‹ thá»‹ trÆ°á»ng xÃ¡c nháº­n yáº¿u.
6. Rá»§i ro dá»¯ liá»‡u vÃ  bÆ°á»›c tiáº¿p theo: data quality, CAR/beta/provision/credit-cycle, vÃ  Ä‘iá»u cáº§n kiá»ƒm tra trÆ°á»›c khi dÃ¹ng tÃ­n hiá»‡u.
"""
    return system_prompt, user_prompt.strip()


def run_ai_analysis(
    api_key: str,
    provider_key: str,
    data: pd.DataFrame,
    ohlcv_source: str = "none",
    focus_question: str = "",
) -> str:
    from openai import OpenAI

    cfg = AI_PROVIDER_MAP.get(provider_key, AI_PROVIDER_MAP["deepseek-v4-pro"])
    system_prompt, user_prompt = build_bank_valuation_ai_prompt(data, ohlcv_source, focus_question)
    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"], timeout=cfg.get("timeout", 180))
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **completion_options(
            model=cfg["api_model"],
            route="child_report",
            temperature=cfg.get("temperature", 0.5),
        ),
    )
    return response.choices[0].message.content
