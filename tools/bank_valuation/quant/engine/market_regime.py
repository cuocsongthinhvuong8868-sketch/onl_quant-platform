from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


REGIME_LABELS = {
    "very_cheap": "Rẻ trên diện rộng",
    "cheap": "Tương đối rẻ",
    "neutral": "Trung tính",
    "expensive": "Định giá cao, cần chọn lọc",
    "broadly_expensive": "Định giá cao trên diện rộng",
    "insufficient": "Chưa đủ dữ liệu",
}

QUALITY_WEIGHTS = {
    "High": 1.0,
    "Medium": 0.6,
    "Low": 0.2,
}


@dataclass(frozen=True)
class BankValuationRegime:
    eligible_banks: int
    overvalued_count: int
    fair_count: int
    strong_undervalued_count: int
    risky_undervalued_count: int
    undervalued_count: int
    overvalued_breadth: float
    fair_breadth: float
    undervalued_breadth: float
    bank_valuation_breadth_score: float
    regime_label: str
    median_valuation_gap: float
    trimmed_mean_valuation_gap: float
    market_cap_weighted_gap: float
    confidence_weighted_gap: float
    relative_value_breadth_score: float
    methodology_note: str

    def to_dict(self) -> dict:
        return {
            "eligible_banks": self.eligible_banks,
            "overvalued_count": self.overvalued_count,
            "fair_count": self.fair_count,
            "strong_undervalued_count": self.strong_undervalued_count,
            "risky_undervalued_count": self.risky_undervalued_count,
            "undervalued_count": self.undervalued_count,
            "overvalued_breadth": self.overvalued_breadth,
            "fair_breadth": self.fair_breadth,
            "undervalued_breadth": self.undervalued_breadth,
            "bank_valuation_breadth_score": self.bank_valuation_breadth_score,
            "regime_label": self.regime_label,
            "median_valuation_gap": self.median_valuation_gap,
            "trimmed_mean_valuation_gap": self.trimmed_mean_valuation_gap,
            "market_cap_weighted_gap": self.market_cap_weighted_gap,
            "confidence_weighted_gap": self.confidence_weighted_gap,
            "relative_value_breadth_score": self.relative_value_breadth_score,
            "methodology_note": self.methodology_note,
        }


def _empty_regime() -> BankValuationRegime:
    return BankValuationRegime(
        eligible_banks=0,
        overvalued_count=0,
        fair_count=0,
        strong_undervalued_count=0,
        risky_undervalued_count=0,
        undervalued_count=0,
        overvalued_breadth=float("nan"),
        fair_breadth=float("nan"),
        undervalued_breadth=float("nan"),
        bank_valuation_breadth_score=float("nan"),
        regime_label=REGIME_LABELS["insufficient"],
        median_valuation_gap=float("nan"),
        trimmed_mean_valuation_gap=float("nan"),
        market_cap_weighted_gap=float("nan"),
        confidence_weighted_gap=float("nan"),
        relative_value_breadth_score=float("nan"),
        methodology_note=_methodology_note(),
    )


def _methodology_note() -> str:
    return (
        "Chỉ báo này suy ra trạng thái thị trường từ độ rộng định giá của nhóm ngân hàng "
        "niêm yết Việt Nam. Mô hình không phân loại thị trường bằng kỹ thuật giá, dòng tiền, "
        "vĩ mô hay P/E toàn thị trường; nó dùng kết quả định giá bottom-up của từng ngân hàng "
        "làm proxy vì ngân hàng là nhóm vốn hóa, thanh khoản và chu kỳ tín dụng cốt lõi của TTCK Việt Nam."
    )


def _regime_label(score: float) -> str:
    if pd.isna(score):
        return REGIME_LABELS["insufficient"]
    if score >= 0.25:
        return REGIME_LABELS["very_cheap"]
    if score >= 0.0:
        return REGIME_LABELS["cheap"]
    if score > -0.25:
        return REGIME_LABELS["neutral"]
    if score > -0.50:
        return REGIME_LABELS["expensive"]
    return REGIME_LABELS["broadly_expensive"]


def _trimmed_mean(values: pd.Series, trim_pct: float = 0.10) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if clean.empty:
        return float("nan")
    trim_count = int(len(clean) * trim_pct)
    if trim_count > 0 and len(clean) > trim_count * 2:
        clean = clean.iloc[trim_count:-trim_count]
    return float(clean.mean())


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    frame = pd.DataFrame({
        "value": pd.to_numeric(values, errors="coerce"),
        "weight": pd.to_numeric(weights, errors="coerce"),
    }).dropna()
    frame = frame[frame["weight"] > 0]
    if frame.empty:
        return float("nan")
    return float((frame["value"] * frame["weight"]).sum() / frame["weight"].sum())


def _relative_value_score(data: pd.DataFrame) -> float:
    if "relative_valuation_label" not in data.columns or data.empty:
        return float("nan")
    weights = {
        "Relatively Cheap": 1.0,
        "Slightly Cheap": 0.5,
        "Peer Fair": 0.0,
        "Slightly Expensive": -0.5,
        "Relatively Expensive": -1.0,
    }
    labels = data["relative_valuation_label"].fillna("")
    scores = labels.map(weights)
    scores = scores.dropna()
    if scores.empty:
        return float("nan")
    return float(scores.sum() / len(data))


def calculate_bank_valuation_regime(data: pd.DataFrame) -> BankValuationRegime:
    if data.empty or "classification" not in data.columns:
        return _empty_regime()

    result = data.copy()
    if "data_quality_flag" in result.columns:
        result = result[result["data_quality_flag"].fillna("Low") != "Low"]
    result = result[result["classification"].notna()]
    if result.empty:
        return _empty_regime()

    labels = result["classification"].fillna("")
    eligible = len(result)
    overvalued = int((labels == "Overvalued").sum())
    fair = int((labels == "Fairly Valued").sum())
    strong_under = int((labels == "Strong Undervalued").sum())
    risky_under = int((labels == "Undervalued but Risky").sum())
    undervalued = strong_under + risky_under

    breadth_score = (strong_under + 0.5 * risky_under - overvalued) / eligible
    valuation_gap = pd.to_numeric(result.get("valuation_gap_pct", pd.Series(dtype=float)), errors="coerce")

    market_cap_weighted_gap = float("nan")
    if {"price", "shares_outstanding"}.issubset(result.columns):
        market_cap = pd.to_numeric(result["price"], errors="coerce") * pd.to_numeric(
            result["shares_outstanding"], errors="coerce"
        )
        market_cap_weighted_gap = _weighted_mean(valuation_gap, market_cap)

    confidence_weighted_gap = float("nan")
    if "confidence_score" in result.columns:
        confidence = pd.to_numeric(result["confidence_score"], errors="coerce") / 100.0
    else:
        confidence = pd.Series(1.0, index=result.index)
    if "data_quality_flag" in result.columns:
        quality = result["data_quality_flag"].map(QUALITY_WEIGHTS).fillna(0.2)
    else:
        quality = pd.Series(1.0, index=result.index)
    confidence_weighted_gap = _weighted_mean(valuation_gap, confidence * quality)

    return BankValuationRegime(
        eligible_banks=eligible,
        overvalued_count=overvalued,
        fair_count=fair,
        strong_undervalued_count=strong_under,
        risky_undervalued_count=risky_under,
        undervalued_count=undervalued,
        overvalued_breadth=overvalued / eligible,
        fair_breadth=fair / eligible,
        undervalued_breadth=undervalued / eligible,
        bank_valuation_breadth_score=breadth_score,
        regime_label=_regime_label(breadth_score),
        median_valuation_gap=float(valuation_gap.median()) if not valuation_gap.dropna().empty else float("nan"),
        trimmed_mean_valuation_gap=_trimmed_mean(valuation_gap),
        market_cap_weighted_gap=market_cap_weighted_gap,
        confidence_weighted_gap=confidence_weighted_gap,
        relative_value_breadth_score=_relative_value_score(result),
        methodology_note=_methodology_note(),
    )
