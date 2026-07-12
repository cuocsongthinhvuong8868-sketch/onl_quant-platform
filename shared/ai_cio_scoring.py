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


def _evt_sensitivity_state(metrics: dict[str, Any], xi: float | None) -> dict[str, Any]:
    """Classify EVT threshold sensitivity as confidence/robustness, not a new signal."""

    xi_min = _as_float(metrics.get("evt_xi_min"))
    xi_max = _as_float(metrics.get("evt_xi_max"))
    xi_range = _as_float(metrics.get("evt_xi_range"))
    stable_raw = metrics.get("evt_threshold_stable")
    stable = None
    if isinstance(stable_raw, bool):
        stable = stable_raw
    elif stable_raw is not None:
        stable_text = str(stable_raw).strip().lower()
        if stable_text in {"1", "true", "yes", "stable"}:
            stable = True
        elif stable_text in {"0", "false", "no", "threshold_sensitive", "sensitive"}:
            stable = False

    if xi_min is None and xi_max is None and xi_range is None:
        return {
            "available": False,
            "xi_min": xi_min,
            "xi_max": xi_max,
            "xi_range": xi_range,
            "stable": stable,
            "robust_fat": xi is not None and xi >= 0.30,
            "robust_elevated": xi is not None and xi >= 0.25,
            "threshold_sensitive_fat": False,
        }

    if xi_min is None and xi_max is not None and xi_range is not None:
        xi_min = xi_max - xi_range
    if xi_max is None and xi_min is not None and xi_range is not None:
        xi_max = xi_min + xi_range
    if xi_range is None and xi_min is not None and xi_max is not None:
        xi_range = xi_max - xi_min
    if stable is None and xi_range is not None:
        stable = xi_range <= 0.10

    robust_fat = xi is not None and xi >= 0.30 and xi_min is not None and xi_min >= 0.30
    robust_elevated = xi is not None and xi >= 0.25 and xi_min is not None and xi_min >= 0.25
    threshold_sensitive_fat = (
        xi is not None
        and xi >= 0.30
        and not robust_fat
        and ((xi_min is not None and xi_min < 0.30) or (stable is False))
    )
    return {
        "available": True,
        "xi_min": xi_min,
        "xi_max": xi_max,
        "xi_range": xi_range,
        "stable": stable,
        "robust_fat": robust_fat,
        "robust_elevated": robust_elevated,
        "threshold_sensitive_fat": threshold_sensitive_fat,
    }


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
        sensitivity = _evt_sensitivity_state(metrics, xi)
        if not sensitivity["available"]:
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
        elif sensitivity["robust_fat"] and xi >= 0.40:
            score = 12
            reason = (
                f"EVT xi >=0.40 ({xi:.3f}) and xi_min across thresholds "
                f">=0.30 ({sensitivity['xi_min']:.3f})"
            )
        elif sensitivity["robust_fat"]:
            score = 18
            reason = (
                f"EVT fat-tail robust across thresholds: xi={xi:.3f}, "
                f"xi_min={sensitivity['xi_min']:.3f}"
            )
        elif sensitivity["robust_elevated"]:
            score = 28
            reason = (
                f"EVT elevated tail robust but not fat across thresholds: xi={xi:.3f}, "
                f"xi_min={sensitivity['xi_min']:.3f}"
            )
        elif sensitivity["threshold_sensitive_fat"]:
            score = 35
            xi_min = sensitivity["xi_min"]
            xi_range = sensitivity["xi_range"]
            reason = f"EVT central xi fat but threshold-sensitive: xi={xi:.3f}"
            if xi_min is not None:
                reason += f", xi_min={xi_min:.3f}"
            if xi_range is not None:
                reason += f", xi_range={xi_range:.3f}"
        elif xi < 0.25 and sensitivity.get("xi_max") is not None and sensitivity["xi_max"] >= 0.30:
            score = 42
            reason = (
                f"EVT upper sensitivity reaches fat-tail zone but base xi is below 0.25: "
                f"xi={xi:.3f}, xi_max={sensitivity['xi_max']:.3f}"
            )
        else:
            score = 55
            reason = f"EVT xi below robust fat-tail threshold ({xi:.3f})"
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

    if tool == "credit_spread":
        premium = _as_float(metrics.get("credit_spread_risk_premium_bps"))
        change = _as_float(metrics.get("credit_spread_change_bps"))
        change_3p = _as_float(metrics.get("credit_spread_3p_change_bps"))
        percentile = _as_float(metrics.get("credit_spread_percentile"))
        matched_periods = _as_float(metrics.get("credit_spread_matched_periods"))
        bank_count = _as_float(metrics.get("credit_spread_bank_count"))
        real_estate_count = _as_float(metrics.get("credit_spread_real_estate_count"))
        if premium is None or percentile is None:
            return None

        if (
            (matched_periods is not None and matched_periods < 8)
            or (bank_count is not None and bank_count < 2)
            or (real_estate_count is not None and real_estate_count < 2)
        ):
            return {
                "tool_score": 50,
                "tool_regime": "CREDIT SPREAD THIN DATA",
                "tool_bias": "neutral_or_mixed",
                "score_reason": "Credit Spread sample too thin for a directional score",
            }

        score = 55.0
        reasons = [f"risk premium {premium:.1f} bps at matched-history percentile {percentile:.1f}"]
        if percentile >= 85:
            score = min(score, 32.0)
        elif percentile >= 70:
            score = min(score, 38.0)
        elif percentile >= 55:
            score = min(score, 45.0)
        elif percentile >= 40:
            score = min(score, 50.0)

        if premium >= 400:
            score = min(score, 35.0)
            reasons.append("absolute premium >=400 bps")
        elif premium >= 300:
            score = min(score, 45.0)
            reasons.append("absolute premium >=300 bps")

        if change is not None:
            if change >= 25:
                score -= 6.0
                reasons.append(f"latest widening {change:+.1f} bps")
            elif change <= -25:
                score += 4.0
                reasons.append(f"latest narrowing {change:+.1f} bps")
        if change_3p is not None:
            if change_3p >= 50:
                score -= 5.0
                reasons.append(f"3P widening {change_3p:+.1f} bps")
            elif change_3p <= -50:
                score += 4.0
                reasons.append(f"3P narrowing {change_3p:+.1f} bps")

        score_int = _bounded(score)
        if score_int <= 35:
            regime = "CREDIT SPREAD STRESSED / WIDENING"
            bias = "bearish"
        elif score_int <= 48:
            regime = "CREDIT SPREAD ELEVATED"
            bias = "bearish"
        else:
            regime = "CREDIT SPREAD NORMALIZING / CONTAINED"
            bias = "neutral_or_mixed"
        return {
            "tool_score": score_int,
            "tool_regime": regime,
            "tool_bias": bias,
            "score_reason": "; ".join(reasons),
        }

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

    if tool == "ltmm":
        fli = _as_float(metrics.get("ltmm_fli"))
        mli = _as_float(metrics.get("ltmm_mli"))
        te = _as_float(metrics.get("ltmm_te"))
        fri_collateral = _as_float(metrics.get("ltmm_fri_collateral"))
        fire_count = _as_float(metrics.get("ltmm_fire_trigger_count"))
        transmission_breakdown = _as_float(metrics.get("ltmm_transmission_breakdown_fire"))
        if (
            fli is None
            and mli is None
            and te is None
            and fri_collateral is None
            and fire_count is None
            and transmission_breakdown is None
        ):
            return None

        score = 55.0
        reasons: list[str] = []
        regime = "LTMM TRANSMISSION NORMAL"
        bias = "neutral_or_mixed"

        if transmission_breakdown is not None and transmission_breakdown >= 1:
            score = min(score, 30.0)
            regime = "LTMM TRANSMISSION BREAKDOWN"
            bias = "bearish"
            reasons.append("transmission_breakdown trigger FIRE")
        elif fire_count is not None and fire_count >= 1:
            score = min(score, 35.0)
            regime = "LTMM FIRE TRIGGER ACTIVE"
            bias = "bearish"
            reasons.append(f"FIRE trigger count >=1 ({fire_count:.0f})")

        if fire_count is not None and fire_count >= 2:
            score = min(score, 25.0)
            regime = "LTMM MULTI-TRIGGER STRESS"
            bias = "bearish"
            reasons.append(f"FIRE trigger count >=2 ({fire_count:.0f})")

        if mli is not None:
            if mli >= 1.0:
                score = min(score, 25.0)
                regime = "LTMM MARKET LIQUIDITY STRESS"
                bias = "bearish"
                reasons.append(f"MLI >=1.0 ({mli:+.3f})")
            elif mli >= 0.75:
                score = min(score, 35.0)
                bias = "bearish"
                reasons.append(f"MLI tightening ({mli:+.3f})")

        if te is not None and te <= -1.0:
            score = min(score, 30.0)
            regime = "LTMM TRANSMISSION BREAKDOWN"
            bias = "bearish"
            reasons.append(f"TE breakdown ({te:+.3f})")

        if fri_collateral is not None and fri_collateral >= 0.75:
            score = min(score, 38.0)
            if score < 45:
                bias = "bearish"
            reasons.append(f"FRI_collateral bottleneck ({fri_collateral:+.3f})")

        if fli is not None and mli is not None and (mli - fli) >= 0.75:
            score = min(score, 38.0)
            if score < 45:
                bias = "bearish"
            reasons.append(f"downstream MLI materially tighter than upstream FLI ({mli - fli:+.3f})")

        score_int = _bounded(score)
        return {
            "tool_score": score_int,
            "tool_regime": regime if score_int < 45 else regime_from_score(score_int),
            "tool_bias": bias if score_int < 45 else bias_from_score(score_int),
            "score_reason": "; ".join(reasons) if reasons else "LTMM metrics not in stress zone",
        }

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

    if tool == "abm_simulator":
        early_warning = _as_float(metrics.get("abm_early_warning_score"))
        distance = _as_float(metrics.get("distance_to_cascade_pct"))
        panic = _as_float(metrics.get("panic_ratio_pct"))
        leverage = _as_float(metrics.get("abm_avg_leverage_ratio"))
        vulnerability = _as_float(metrics.get("cascade_vulnerability"))
        if early_warning is None and distance is None and panic is None and leverage is None and vulnerability is None:
            return None

        score = 58.0
        reasons: list[str] = []
        regime = "ABM GREEN EARLY WARNING"
        bias = "neutral_or_mixed"

        if early_warning is not None:
            if early_warning >= 75:
                score = min(score, 15.0)
                regime = "ABM RED EARLY WARNING / CASCADE RISK"
                bias = "bearish"
                reasons.append(f"Early-warning score >=75 ({early_warning:.1f}/100)")
            elif early_warning >= 60:
                score = min(score, 25.0)
                regime = "ABM ORANGE EARLY WARNING / STRESS RISING"
                bias = "bearish"
                reasons.append(f"Early-warning score >=60 ({early_warning:.1f}/100)")
            elif early_warning >= 45:
                score = min(score, 42.0)
                regime = "ABM YELLOW EARLY WARNING / FRAGILITY WATCH"
                bias = "bearish"
                reasons.append(f"Early-warning score >=45 ({early_warning:.1f}/100)")
            else:
                score = min(score, 60.0)
                regime = "ABM GREEN EARLY WARNING"
                reasons.append(f"Early-warning score below yellow ({early_warning:.1f}/100)")

        if distance is not None:
            if distance <= 2:
                score = min(score, 12.0)
                regime = "ABM CASCADE WARNING"
                bias = "bearish"
                reasons.append(f"Distance to cascade <=2% ({distance:.2f}%)")
            elif distance <= 5:
                score = min(score, 42.0 if early_warning is not None else 25.0)
                if early_warning is None:
                    regime = "ABM LEVERAGE STRESS"
                bias = "bearish"
                reasons.append(f"Distance to cascade <=5% ({distance:.2f}%)")
            elif distance <= 10:
                score = min(score, 45.0 if early_warning is not None else 38.0)
                if early_warning is None:
                    regime = "ABM MARGIN BUILDUP"
                    bias = "bearish"
                reasons.append(f"Distance to cascade <=10% ({distance:.2f}%)")
            else:
                reasons.append(f"Distance to cascade contained ({distance:.2f}%)")

        if panic is not None:
            if panic >= 50:
                score = min(score, 18.0)
                regime = "ABM FORCED-SELLING STRESS"
                bias = "bearish"
                reasons.append(f"Panic ratio >=50% ({panic:.2f}%)")
            elif panic >= 30:
                score = min(score, 30.0)
                bias = "bearish"
                reasons.append(f"Panic ratio >=30% ({panic:.2f}%)")
            elif panic >= 15:
                score = min(score, 42.0)
                reasons.append(f"Panic ratio elevated ({panic:.2f}%)")

        if leverage is not None and leverage >= 2.5:
            score = min(score, 42.0)
            reasons.append(f"Avg leverage >=2.5x ({leverage:.2f}x)")

        if vulnerability is not None and vulnerability >= 0.65:
            score = min(score, 35.0)
            bias = "bearish"
            reasons.append(f"Cascade vulnerability high ({vulnerability:.2f})")

        score_int = _bounded(score)
        return {
            "tool_score": score_int,
            "tool_regime": regime,
            "tool_bias": bias,
            "score_reason": "; ".join(reasons) if reasons else "ABM cascade metrics not in stress zone",
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
    xi_min_values = values_for(".evt_xi_min")
    xi_max_values = values_for(".evt_xi_max")
    xi_range_values = values_for(".evt_xi_range")
    evt_threshold_stable_values = values_for(".evt_threshold_stable")
    pvgo_values = values_for(".pvgo_pct")
    abm_early_warning_values = values_for(".abm_early_warning_score")
    abm_distance_values = values_for(".distance_to_cascade_pct")
    abm_panic_values = values_for(".panic_ratio_pct")
    abm_vulnerability_values = values_for(".cascade_vulnerability")
    ltmm_fli_values = values_for(".ltmm_fli")
    ltmm_mli_values = values_for(".ltmm_mli")
    ltmm_te_values = values_for(".ltmm_te")
    ltmm_fri_values = values_for(".ltmm_fri_collateral")
    ltmm_fire_values = values_for(".ltmm_fire_trigger_count")
    ltmm_breakdown_values = values_for(".ltmm_transmission_breakdown_fire")

    max_cqs = max(cqs_values) if cqs_values else None
    max_vnibor = max(vnibor_values) if vnibor_values else None
    min_breadth = min(breadth_values) if breadth_values else None
    max_ssi = max(ssi_values) if ssi_values else None
    max_xi = max(xi_values) if xi_values else None
    min_xi_sensitivity = min(xi_min_values) if xi_min_values else None
    max_xi_sensitivity = max(xi_max_values) if xi_max_values else None
    max_xi_range = max(xi_range_values) if xi_range_values else None
    evt_threshold_stable = None
    if evt_threshold_stable_values:
        evt_threshold_stable = 1.0 if all(value >= 0.5 for value in evt_threshold_stable_values) else 0.0
    evt_sensitivity = _evt_sensitivity_state(
        {
            "evt_xi_min": min_xi_sensitivity,
            "evt_xi_max": max_xi_sensitivity,
            "evt_xi_range": max_xi_range,
            "evt_threshold_stable": evt_threshold_stable,
        },
        max_xi,
    )
    max_pvgo = max(pvgo_values) if pvgo_values else None
    max_abm_early_warning = max(abm_early_warning_values) if abm_early_warning_values else None
    min_abm_distance = min(abm_distance_values) if abm_distance_values else None
    max_abm_panic = max(abm_panic_values) if abm_panic_values else None
    max_abm_vulnerability = max(abm_vulnerability_values) if abm_vulnerability_values else None
    min_ltmm_fli = min(ltmm_fli_values) if ltmm_fli_values else None
    max_ltmm_mli = max(ltmm_mli_values) if ltmm_mli_values else None
    min_ltmm_te = min(ltmm_te_values) if ltmm_te_values else None
    max_ltmm_fri = max(ltmm_fri_values) if ltmm_fri_values else None
    max_ltmm_fire = max(ltmm_fire_values) if ltmm_fire_values else None
    max_ltmm_breakdown = max(ltmm_breakdown_values) if ltmm_breakdown_values else None

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
    if max_ltmm_breakdown is not None and max_ltmm_breakdown >= 1:
        macro_score = min(macro_score, 30.0)
        macro_reasons.append("LTMM transmission_breakdown trigger FIRE")
    elif max_ltmm_fire is not None and max_ltmm_fire >= 1:
        macro_score = min(macro_score, 35.0)
        macro_reasons.append(f"LTMM FIRE trigger count >=1 ({max_ltmm_fire:.0f})")
    if max_ltmm_fire is not None and max_ltmm_fire >= 2:
        macro_score = min(macro_score, 25.0)
        macro_reasons.append(f"LTMM FIRE trigger count >=2 ({max_ltmm_fire:.0f})")
    if max_ltmm_mli is not None:
        if max_ltmm_mli >= 1.0:
            macro_score = min(macro_score, 25.0)
            macro_reasons.append(f"LTMM MLI >=1.0 ({max_ltmm_mli:+.3f})")
        elif max_ltmm_mli >= 0.75:
            macro_score = min(macro_score, 35.0)
            macro_reasons.append(f"LTMM MLI tightening ({max_ltmm_mli:+.3f})")
    if min_ltmm_te is not None and min_ltmm_te <= -1.0:
        macro_score = min(macro_score, 30.0)
        macro_reasons.append(f"LTMM TE breakdown ({min_ltmm_te:+.3f})")
    if max_ltmm_fri is not None and max_ltmm_fri >= 0.75:
        macro_score = min(macro_score, 40.0)
        macro_reasons.append(f"LTMM FRI_collateral bottleneck ({max_ltmm_fri:+.3f})")
    if min_ltmm_fli is not None and max_ltmm_mli is not None and (max_ltmm_mli - min_ltmm_fli) >= 0.75:
        macro_score = min(macro_score, 38.0)
        macro_reasons.append(
            f"LTMM downstream MLI materially tighter than upstream FLI ({max_ltmm_mli - min_ltmm_fli:+.3f})"
        )
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
        if not evt_sensitivity["available"]:
            if max_xi >= 0.40:
                tail_score = min(tail_score, 12.0)
                tail_reasons.append(f"EVT xi >=0.40 ({max_xi:.3f})")
            elif max_xi >= 0.30:
                tail_score = min(tail_score, 18.0)
                tail_reasons.append(f"EVT xi >=0.30 ({max_xi:.3f})")
            elif max_xi >= 0.25:
                tail_score = min(tail_score, 28.0)
                tail_reasons.append(f"EVT xi >=0.25 ({max_xi:.3f})")
        elif evt_sensitivity["robust_fat"] and max_xi >= 0.40:
            tail_score = min(tail_score, 12.0)
            tail_reasons.append(
                f"EVT fat tail robust across thresholds: xi={max_xi:.3f}, xi_min={evt_sensitivity['xi_min']:.3f}"
            )
        elif evt_sensitivity["robust_fat"]:
            tail_score = min(tail_score, 18.0)
            tail_reasons.append(
                f"EVT fat tail robust across thresholds: xi={max_xi:.3f}, xi_min={evt_sensitivity['xi_min']:.3f}"
            )
        elif evt_sensitivity["robust_elevated"]:
            tail_score = min(tail_score, 28.0)
            tail_reasons.append(
                f"EVT elevated tail robust across thresholds: xi={max_xi:.3f}, xi_min={evt_sensitivity['xi_min']:.3f}"
            )
        elif evt_sensitivity["threshold_sensitive_fat"]:
            tail_score = min(tail_score, 35.0)
            reason = f"EVT xi threshold-sensitive: xi={max_xi:.3f}"
            if evt_sensitivity["xi_min"] is not None:
                reason += f", xi_min={evt_sensitivity['xi_min']:.3f}"
            if evt_sensitivity["xi_range"] is not None:
                reason += f", xi_range={evt_sensitivity['xi_range']:.3f}"
            tail_reasons.append(reason)
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
    if max_abm_early_warning is not None:
        if max_abm_early_warning >= 75:
            tail_score = min(tail_score, 15.0)
            tail_reasons.append(f"ABM early-warning score RED >=75 ({max_abm_early_warning:.1f}/100)")
        elif max_abm_early_warning >= 60:
            tail_score = min(tail_score, 25.0)
            tail_reasons.append(f"ABM early-warning score ORANGE >=60 ({max_abm_early_warning:.1f}/100)")
        elif max_abm_early_warning >= 45:
            tail_score = min(tail_score, 42.0)
            tail_reasons.append(f"ABM early-warning score YELLOW >=45 ({max_abm_early_warning:.1f}/100)")
    if min_abm_distance is not None:
        if min_abm_distance <= 2:
            tail_score = min(tail_score, 12.0)
            tail_reasons.append(f"ABM distance to cascade <=2% ({min_abm_distance:.2f}%)")
        elif min_abm_distance <= 5:
            tail_score = min(tail_score, 42.0 if max_abm_early_warning is not None else 25.0)
            tail_reasons.append(f"ABM distance to cascade <=5% ({min_abm_distance:.2f}%)")
        elif min_abm_distance <= 10:
            tail_score = min(tail_score, 45.0 if max_abm_early_warning is not None else 38.0)
            tail_reasons.append(f"ABM distance to cascade <=10% ({min_abm_distance:.2f}%)")
    if max_abm_panic is not None:
        if max_abm_panic >= 50:
            tail_score = min(tail_score, 18.0)
            tail_reasons.append(f"ABM panic ratio >=50% ({max_abm_panic:.1f}%)")
        elif max_abm_panic >= 30:
            tail_score = min(tail_score, 30.0)
            tail_reasons.append(f"ABM panic ratio >=30% ({max_abm_panic:.1f}%)")
        elif max_abm_panic >= 15:
            tail_score = min(tail_score, 42.0)
            tail_reasons.append(f"ABM panic ratio >=15% ({max_abm_panic:.1f}%)")
    if max_abm_vulnerability is not None and max_abm_vulnerability >= 0.65:
        tail_score = min(tail_score, 35.0)
        tail_reasons.append(f"ABM cascade vulnerability high ({max_abm_vulnerability:.2f})")

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
    if evt_sensitivity["robust_fat"] and max_ssi is not None and max_ssi >= 80:
        weighted = min(weighted, 14.0)
        caps.append("EXTREME CRISIS cap: EVT xi robustly >=0.30 across thresholds and SSI >=80%")
    elif evt_sensitivity["robust_fat"]:
        weighted = min(weighted, 29.0)
        caps.append("PRE-CRASH cap: EVT xi robustly >=0.30 across thresholds")
    elif evt_sensitivity["threshold_sensitive_fat"]:
        caps.append("No EVT hard cap: central xi >=0.30 is threshold-sensitive")
    if min_breadth is not None and min_breadth < 45:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: Breadth MA20 <45%")
    if max_cqs is not None and max_cqs >= 80:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: CQS >=80")
    if max_abm_early_warning is not None and max_abm_early_warning >= 75:
        weighted = min(weighted, 29.0)
        caps.append("PRE-CRASH cap: ABM early-warning score RED >=75")
    elif max_abm_early_warning is not None and max_abm_early_warning >= 60:
        weighted = min(weighted, 39.0)
        caps.append("FEAR cap: ABM early-warning score ORANGE >=60")
    elif max_abm_early_warning is not None and max_abm_early_warning >= 45:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: ABM early-warning score YELLOW >=45")
    if (
        max_ltmm_breakdown is not None
        and max_ltmm_breakdown >= 1
        and max_ltmm_mli is not None
        and max_ltmm_mli >= 0.75
    ):
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: LTMM transmission breakdown and MLI tightening")
    if min_abm_distance is not None and min_abm_distance <= 5:
        weighted = min(weighted, 44.0)
        caps.append("FEAR cap: ABM distance to cascade <=5%")
    if (
        min_abm_distance is not None
        and min_abm_distance <= 2
        and max_abm_panic is not None
        and max_abm_panic >= 30
    ):
        weighted = min(weighted, 29.0)
        caps.append("PRE-CRASH cap: ABM distance <=2% and panic ratio >=30%")

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
