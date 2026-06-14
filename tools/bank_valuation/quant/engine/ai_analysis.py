from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime


AI_PROVIDER_MAP = {
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
        "api_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "temperature": 0.5,
    },
    "kimi-2.6": {
        "display": "Kimi 2.6",
        "api_model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
        "temperature": 1.0,
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
        return "Chưa đủ dữ liệu hợp lệ để phân loại trạng thái thị trường theo định giá nhóm ngân hàng."

    return f"""
Phân loại regime: {regime.regime_label}
Mã hợp lệ: {regime.eligible_banks}
Định giá cao: {regime.overvalued_count} ({_format_pct(regime.overvalued_breadth)})
Hợp lý: {regime.fair_count} ({_format_pct(regime.fair_breadth)})
Rẻ rõ rệt: {regime.strong_undervalued_count}
Rẻ nhưng rủi ro: {regime.risky_undervalued_count}
Điểm độ rộng định giá: {_format_pct(regime.bank_valuation_breadth_score)}
Gap trung vị: {_format_pct(regime.median_valuation_gap)}
Gap trimmed mean: {_format_pct(regime.trimmed_mean_valuation_gap)}
Gap theo vốn hóa: {_format_pct(regime.market_cap_weighted_gap)}
Gap theo chất lượng dữ liệu: {_format_pct(regime.confidence_weighted_gap)}
Điểm định giá tương đối theo peer labels: {_format_pct(regime.relative_value_breadth_score)}

Phương pháp: {regime.methodology_note}
Công thức điểm độ rộng: (Rẻ rõ rệt + 0.5 x Rẻ nhưng rủi ro - Định giá cao) / số mã hợp lệ.
Ngưỡng đọc regime: >= +25% là Rẻ trên diện rộng; 0% đến +25% là Tương đối rẻ; -25% đến 0% là Trung tính; -50% đến -25% là Định giá cao, cần chọn lọc; dưới -50% là Định giá cao trên diện rộng.
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
- Ngày báo cáo AI: {report_date_text}
- Tickers: {len(data)}
- Overvalued: {counts["overvalued"]}
- Fair value: {counts["fair"]}
- Undervalued: {counts["undervalued"]}
- Other / need more data: {counts["other"]}
- OHLCV source: {ohlcv_source}

## Trạng thái thị trường hàm ý từ định giá nhóm ngân hàng
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
1. Dòng mở đầu: ghi rõ "Ngày báo cáo AI: {report_date_text}".
2. Phân loại regime: nêu rõ nhãn "Trạng thái thị trường hàm ý từ định giá nhóm ngân hàng", điểm độ rộng, số mã định giá cao / hợp lý / rẻ, và kết luận biên an toàn hiện tại.
3. Luận điểm chính: 3-5 bullets giải thích vì sao regime đó được suy ra từ valuation breadth của nhóm ngân hàng.
4. Kiểm tra chéo: định giá tương đối và xác nhận giá đang củng cố hay phủ định kết luận regime.
5. Tín hiệu theo mã: mã nào đáng theo dõi trong nhóm hợp lý/rẻ, mã nào là rủi ro hoặc đang bị thị trường xác nhận yếu.
6. Rủi ro dữ liệu và bước tiếp theo: data quality, CAR/beta/provision/credit-cycle, và điều cần kiểm tra trước khi dùng tín hiệu.
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
    client = OpenAI(api_key=api_key.strip(), base_url=cfg["base_url"])
    response = client.chat.completions.create(
        model=cfg["api_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=cfg.get("temperature", 0.5),
    )
    return response.choices[0].message.content
