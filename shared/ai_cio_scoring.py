from __future__ import annotations

from typing import Any


def regime_from_score(score: float) -> str:
    if score <= 7:
        return "CAPITULATION"
    if score <= 14:
        return "EXTREME CRISIS"
    if score <= 29:
        return "PRE-CRASH / PANIC"
    if score <= 44:
        return "FEAR / DISTRIBUTION"
    if score <= 59:
        return "NEUTRAL / STOCK-PICKING"
    if score <= 74:
        return "UPTREND / EXPANSION"
    if score <= 89:
        return "BULL CONFIRMED"
    return "EXTREME GREED / TOP WARNING"


def bias_from_score(score: float) -> str:
    if score < 40:
        return "bearish"
    if score > 60:
        return "bullish"
    return "neutral_or_mixed"


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _bounded(score: float) -> int:
    return int(round(max(0.0, min(100.0, score))))


def score_tool_packet(tool_id: str, metrics: dict[str, Any]) -> dict[str, Any] | None:
    """Return a deterministic per-tool score when enough metrics are available."""
    tool = str(tool_id or "")

    if tool in {"market_breadth", "historical_trend"}:
        breadth = _as_float(metrics.get("breadth_ma20_pct"))
        if breadth is None:
            return None
        if breadth < 25:
            score = 18
            reason = f"Breadth MA20 <25% ({breadth:.1f}%)"
        elif breadth < 45:
            score = 35
            reason = f"Breadth MA20 <45% ({breadth:.1f}%)"
        elif breadth < 55:
            score = 45
            reason = f"Breadth MA20 below neutral ({breadth:.1f}%)"
        else:
            score = 60
            reason = f"Breadth MA20 constructive ({breadth:.1f}%)"
        return _tool_score(tool, score, reason)

    if tool == "esr_monitor":
        ssi = _as_float(metrics.get("ssi_pct"))
        if ssi is None:
            return None
        if ssi >= 80:
            score = 18
            reason = f"SSI >=80% ({ssi:.1f}%)"
        elif ssi >= 65:
            score = 35
            reason = f"SSI >=65% ({ssi:.1f}%)"
        elif ssi >= 55:
            score = 42
            reason = f"SSI >=55% ({ssi:.1f}%)"
        else:
            score = 58
            reason = f"SSI below stress threshold ({ssi:.1f}%)"
        return _tool_score(tool, score, reason)

    if tool == "var_cvar_vnindex":
        xi = _as_float(metrics.get("evt_xi"))
        if xi is None:
            return None
        if xi >= 0.40:
            score = 12
            reason = f"EVT xi >=0.40 ({xi:.3f})"
        elif xi >= 0.30:
            score = 18
            reason = f"EVT xi >=0.30 ({xi:.3f})"
        elif xi >= 0.25:
            score = 28
            reason = f"EVT xi >=0.25 ({xi:.3f})"
        else:
            score = 55
            reason = f"EVT xi below fat-tail threshold ({xi:.3f})"
        return _tool_score(tool, score, reason)

    if tool == "global_financial_conditions":
        cqs = _as_float(metrics.get("cqs_percentile"))
        if cqs is None:
            return None
        if cqs >= 85:
            score = 20
            reason = f"CQS >=85 ({cqs:.1f})"
        elif cqs >= 80:
            score = 28
            reason = f"CQS >=80 ({cqs:.1f})"
        elif cqs >= 70:
            score = 38
            reason = f"CQS >=70 ({cqs:.1f})"
        else:
            score = 55
            reason = f"CQS not in stress zone ({cqs:.1f})"
        return _tool_score(tool, score, reason)

    if tool == "vnibor":
        overnight = _as_float(metrics.get("vnibor_on"))
        if overnight is None:
            return None
        if overnight >= 5:
            score = 25
            reason = f"VNIBOR ON >=5% ({overnight:.2f}%)"
        elif overnight >= 4:
            score = 35
            reason = f"VNIBOR ON >=4% ({overnight:.2f}%)"
        elif overnight >= 3:
            score = 45
            reason = f"VNIBOR ON elevated ({overnight:.2f}%)"
        else:
            score = 58
            reason = f"VNIBOR ON contained ({overnight:.2f}%)"
        return _tool_score(tool, score, reason)

    if tool == "pvgo":
        pvgo = _as_float(metrics.get("pvgo_pct"))
        if pvgo is None:
            return None
        if pvgo >= 65:
            score = 25
            regime = "PVGO EXTREME EXPECTATION RISK"
            bias = "bearish"
            reason = f"PVGO extreme expectations ({pvgo:.1f}%)"
        elif pvgo >= 50:
            score = 35
            regime = "PVGO VERY HIGH EXPECTATION RISK"
            bias = "bearish"
            reason = f"PVGO very high expectations ({pvgo:.1f}%)"
        elif pvgo >= 35:
            score = 42
            regime = "PVGO ELEVATED EXPECTATION RISK"
            bias = "bearish"
            reason = f"PVGO elevated expectations ({pvgo:.1f}%)"
        elif pvgo >= 20:
            score = 55
            regime = "PVGO NORMAL / FAIR EXPECTATIONS"
            bias = "neutral_or_mixed"
            reason = f"PVGO fair expectations ({pvgo:.1f}%)"
        elif pvgo >= 0:
            score = 65
            regime = "PVGO LOW EXPECTATIONS"
            bias = "bullish"
            reason = f"PVGO low expectations ({pvgo:.1f}%)"
        else:
            score = 68
            regime = "PVGO BELOW STEADY-STATE VALUE"
            bias = "bullish"
            reason = f"PVGO below steady-state value ({pvgo:.1f}%)"
        return {
            "tool_score": _bounded(score),
            "tool_regime": regime,
            "tool_bias": bias,
            "score_reason": reason,
        }

    return None


def _tool_score(tool: str, score: float, reason: str) -> dict[str, Any]:
    score_int = _bounded(score)
    return {
        "tool_score": score_int,
        "tool_regime": regime_from_score(score_int),
        "tool_bias": bias_from_score(score_int),
        "score_reason": reason,
    }


def derive_metric_implied_scores(
    metric_values: dict[str, Any],
    bias_counts: dict[str, int],
    tool_scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produce an independent current-day score anchor from hard metrics, not history."""

    def values_for(suffix: str) -> list[float]:
        out: list[float] = []
        for key, value in metric_values.items():
            if not str(key).endswith(suffix):
                continue
            number = _as_float(value)
            if number is not None:
                out.append(number)
        return out

    cqs_values = values_for(".cqs_percentile")
    vnibor_values = values_for(".vnibor_on")
    breadth_values = values_for(".breadth_ma20_pct")
    ssi_values = values_for(".ssi_pct")
    xi_values = values_for(".evt_xi")
    pvgo_values = values_for(".pvgo_pct")

    max_cqs = max(cqs_values) if cqs_values else None
    max_vnibor = max(vnibor_values) if vnibor_values else None
    min_breadth = min(breadth_values) if breadth_values else None
    max_ssi = max(ssi_values) if ssi_values else None
    max_xi = max(xi_values) if xi_values else None
    max_pvgo = max(pvgo_values) if pvgo_values else None

    macro_score = 50.0
    macro_reasons: list[str] = []
    if max_cqs is not None:
        if max_cqs >= 85:
            macro_score = min(macro_score, 20.0)
            macro_reasons.append(f"CQS >=85 ({max_cqs:.1f})")
        elif max_cqs >= 80:
            macro_score = min(macro_score, 28.0)
            macro_reasons.append(f"CQS >=80 ({max_cqs:.1f})")
        elif max_cqs >= 70:
            macro_score = min(macro_score, 38.0)
            macro_reasons.append(f"CQS >=70 ({max_cqs:.1f})")
    if max_vnibor is not None:
        if max_vnibor >= 5:
            macro_score = min(macro_score, 25.0)
            macro_reasons.append(f"VNIBOR ON >=5% ({max_vnibor:.2f}%)")
        elif max_vnibor >= 4:
            macro_score = min(macro_score, 35.0)
            macro_reasons.append(f"VNIBOR ON >=4% ({max_vnibor:.2f}%)")
    if bias_counts.get("bearish", 0) >= bias_counts.get("bullish", 0) + 5:
        macro_score = max(0.0, macro_score - 5.0)
        macro_reasons.append("broad bearish evidence balance")

    internal_score = 50.0
    internal_reasons: list[str] = []
    if min_breadth is not None:
        if min_breadth < 25:
            internal_score = 18.0
            internal_reasons.append(f"Breadth MA20 <25% ({min_breadth:.1f}%)")
        elif min_breadth < 45:
            internal_score = 35.0
            internal_reasons.append(f"Breadth MA20 <45% ({min_breadth:.1f}%)")
        elif min_breadth < 55:
            internal_score = 45.0
            internal_reasons.append(f"Breadth MA20 below neutral ({min_breadth:.1f}%)")
        else:
            internal_score = 60.0
            internal_reasons.append(f"Breadth MA20 constructive ({min_breadth:.1f}%)")
    if bias_counts.get("bearish", 0) >= bias_counts.get("bullish", 0) + 7:
        internal_score = max(0.0, internal_score - 5.0)
        internal_reasons.append("current-tool consensus skewed bearish")
    if max_pvgo is not None:
        if max_pvgo >= 65:
            internal_score = min(internal_score, 35.0)
            internal_reasons.append(f"PVGO extreme expectations ({max_pvgo:.1f}%)")
        elif max_pvgo >= 50:
            internal_score = min(internal_score, 42.0)
            internal_reasons.append(f"PVGO very high expectations ({max_pvgo:.1f}%)")
        elif max_pvgo >= 35:
            internal_score = min(internal_score, 45.0)
            internal_reasons.append(f"PVGO elevated expectations ({max_pvgo:.1f}%)")
        elif max_pvgo < 20:
            internal_score = max(internal_score, 58.0)
            internal_reasons.append(f"PVGO low embedded expectations ({max_pvgo:.1f}%)")

    tail_score = 50.0
    tail_reasons: list[str] = []
    if max_xi is not None:
        if max_xi >= 0.40:
            tail_score = min(tail_score, 12.0)
            tail_reasons.append(f"EVT xi >=0.40 ({max_xi:.3f})")
        elif max_xi >= 0.30:
            tail_score = min(tail_score, 18.0)
            tail_reasons.append(f"EVT xi >=0.30 ({max_xi:.3f})")
        elif max_xi >= 0.25:
            tail_score = min(tail_score, 28.0)
            tail_reasons.append(f"EVT xi >=0.25 ({max_xi:.3f})")
    if max_ssi is not None:
        if max_ssi >= 80:
            tail_score = min(tail_score, 18.0)
            tail_reasons.append(f"SSI >=80% ({max_ssi:.1f}%)")
        elif max_ssi >= 65:
            tail_score = min(tail_score, 35.0)
            tail_reasons.append(f"SSI >=65% ({max_ssi:.1f}%)")
        elif max_ssi >= 55:
            tail_score = min(tail_score, 42.0)
            tail_reasons.append(f"SSI >=55% ({max_ssi:.1f}%)")

    weighted = 0.35 * macro_score + 0.35 * internal_score + 0.30 * tail_score
    if tool_scores:
        numeric_scores = [
            float(item["tool_score"])
            for item in tool_scores
            if item.get("tool_score") is not None
        ]
        if numeric_scores:
            weighted = 0.7 * weighted + 0.3 * (sum(numeric_scores) / len(numeric_scores))

    caps: list[str] = []
    if max_xi is not None and max_xi >= 0.30 and max_ssi is not None and max_ssi >= 80:
        weighted = min(weighted, 14.0)
        caps.append("EXTREME CRISIS cap: EVT xi >=0.30 and SSI >=80%")
    elif max_xi is not None and max_xi >= 0.30:
        weighted = min(weighted, 29.0)
        caps.append("PRE-CRASH cap: EVT xi >=0.30")
    if min_breadth is not None and min_breadth < 45:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: Breadth MA20 <45%")
    if max_cqs is not None and max_cqs >= 80:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: CQS >=80")

    score = _bounded(weighted)
    return {
        "macro_risk_score": _bounded(macro_score),
        "market_internal_score": _bounded(internal_score),
        "tail_risk_score": _bounded(tail_score),
        "metric_implied_score": score,
        "metric_implied_regime": regime_from_score(score),
        "tool_score_count": len(tool_scores or []),
        "score_band_reason": {
            "macro": macro_reasons or ["No hard macro stress metric extracted"],
            "market_internal": internal_reasons or ["No hard breadth/internal metric extracted"],
            "tail": tail_reasons or ["No hard tail metric extracted"],
            "caps": caps or ["No score cap triggered"],
        },
    }
