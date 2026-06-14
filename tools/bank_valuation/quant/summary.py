from __future__ import annotations

import pandas as pd

from tools.bank_valuation.quant.engine.market_regime import calculate_bank_valuation_regime


CLASSIFICATION_ORDER = [
    "Strong Undervalued",
    "Undervalued but Risky",
    "Fairly Valued",
    "Overvalued",
    "Value Trap Warning",
    "Neutral / Need More Data",
]

CLASSIFICATION_LABELS_VI = {
    "Strong Undervalued": "Rẻ rõ rệt",
    "Undervalued but Risky": "Rẻ nhưng rủi ro",
    "Fairly Valued": "Định giá hợp lý",
    "Overvalued": "Định giá cao",
    "Value Trap Warning": "Cảnh báo bẫy giá trị",
    "Neutral / Need More Data": "Trung tính / thiếu dữ liệu",
}

RELATIVE_VALUE_LABELS_VI = {
    "Relatively Cheap": "Rẻ hơn nhóm so sánh",
    "Slightly Cheap": "Hơi rẻ hơn nhóm so sánh",
    "Peer Fair": "Ngang nhóm so sánh",
    "Slightly Expensive": "Hơi đắt hơn nhóm so sánh",
    "Relatively Expensive": "Đắt hơn nhóm so sánh",
    "Relative Value Unavailable": "Thiếu dữ liệu tương đối",
}


def eligible_valuation_data(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty or "classification" not in data.columns:
        return data.iloc[0:0].copy()
    result = data.copy()
    if "data_quality_flag" in result.columns:
        result = result[result["data_quality_flag"].fillna("Low") != "Low"]
    return result[result["classification"].notna()].copy()


def latest_period(data: pd.DataFrame) -> str:
    if "period" not in data.columns or data["period"].dropna().empty:
        return "n/a"
    return str(data["period"].dropna().mode().iloc[0])


def classification_summary(data: pd.DataFrame) -> pd.DataFrame:
    result = eligible_valuation_data(data)
    if result.empty:
        return pd.DataFrame(columns=["classification", "label_vi", "count", "share"])
    counts = result["classification"].value_counts().reindex(CLASSIFICATION_ORDER, fill_value=0)
    summary = counts.rename_axis("classification").reset_index(name="count")
    summary["label_vi"] = summary["classification"].map(CLASSIFICATION_LABELS_VI).fillna(summary["classification"])
    summary["share"] = summary["count"] / len(result)
    return summary


def fmt_pct(value: float, digits: int = 1, signed: bool = False) -> str:
    if pd.isna(value):
        return "n/a"
    sign = "+" if signed else ""
    return f"{float(value) * 100:{sign}.{digits}f}%"


def fmt_number(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def fmt_price(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{float(value):,.0f}"


def build_display_table(data: pd.DataFrame) -> pd.DataFrame:
    result = eligible_valuation_data(data)
    if result.empty:
        return pd.DataFrame()

    result = result.copy()
    result["classification_vi"] = result["classification"].map(CLASSIFICATION_LABELS_VI).fillna(result["classification"])
    if "relative_valuation_label" in result.columns:
        result["relative_valuation_vi"] = result["relative_valuation_label"].map(RELATIVE_VALUE_LABELS_VI).fillna(
            result["relative_valuation_label"]
        )
    else:
        result["relative_valuation_vi"] = "n/a"

    table = pd.DataFrame({
        "Mã": result.get("ticker"),
        "Kỳ dữ liệu": result.get("period", "n/a"),
        "Giá": result.get("price"),
        "Fair value RIM": result.get("fair_value_per_share_rim"),
        "Stress value": result.get("stress_value_per_share"),
        "P/B thị trường": result.get("market_pb"),
        "P/B hợp lý": result.get("justified_pb"),
        "Gap định giá": result.get("valuation_gap_pct"),
        "Rủi ro tổng hợp": result.get("overall_risk_score"),
        "Kết luận": result["classification_vi"],
        "Định giá tương đối": result["relative_valuation_vi"],
        "Xác nhận giá": result.get("market_confirmation_label", "n/a"),
        "Chất lượng dữ liệu": result.get("data_quality_flag", "n/a"),
        "Độ tin cậy": result.get("confidence_score", "n/a"),
    })

    for col in ["Giá", "Fair value RIM", "Stress value"]:
        table[col] = pd.to_numeric(table[col], errors="coerce").map(fmt_price)
    for col in ["P/B thị trường", "P/B hợp lý"]:
        table[col] = pd.to_numeric(table[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
    table["Gap định giá"] = pd.to_numeric(table["Gap định giá"], errors="coerce").map(lambda x: fmt_pct(x, signed=True))
    table["Rủi ro tổng hợp"] = pd.to_numeric(table["Rủi ro tổng hợp"], errors="coerce").map(fmt_number)
    table["Độ tin cậy"] = pd.to_numeric(table["Độ tin cậy"], errors="coerce").map(
        lambda x: f"{x:.0f}/100" if pd.notna(x) else "n/a"
    )
    return table
