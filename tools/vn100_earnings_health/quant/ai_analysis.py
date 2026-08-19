from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from shared.llm_policy import completion_options
from .config import AI_CACHE_DIR, AI_PROVIDER_MAP, AI_TEMPERATURE, PROJECT_ROOT, PROMPT_DIR


PROMPT_PATH = PROMPT_DIR / "vn100_earnings_health_promt.md"


def load_project_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    load_dotenv(PROJECT_ROOT / ".env", override=False)


load_project_env()

AI_CIO_CACHE_VERSION_HEADER = "ai-cio-cache-version"
VN100_AI_CACHE_VERSION = "structured_yoy_v1"


def encode_vn100_ai_cache(content: str) -> str:
    marker = f"<!-- {AI_CIO_CACHE_VERSION_HEADER}: {VN100_AI_CACHE_VERSION} -->\n"
    text = str(content or "")
    if text.startswith(marker):
        return text
    return marker + text


def fmt_score(value: Any, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.{digits}f}%"


def fmt_signed_score(value: Any, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):+.{digits}f}"


def to_float(value: Any, default: float = float("nan")) -> float:
    if pd.isna(value):
        return default
    try:
        return float(value)
    except Exception:
        return default


def frame_to_markdown(df: pd.DataFrame, max_rows: int = 12) -> str:
    if df is None or df.empty:
        return "N/A"
    return df.head(max_rows).to_string(index=False)


def cap_weighted_score(frame: pd.DataFrame, score_col: str = "corporate_health_score") -> float:
    values = pd.to_numeric(frame[score_col], errors="coerce")
    weights = pd.to_numeric(frame["market_cap"], errors="coerce")
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return float(values.mean())
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def sector_ticker_list(frame: pd.DataFrame, limit: int = 3) -> str:
    if frame.empty or "ticker" not in frame:
        return "N/A"
    tickers = (
        frame.sort_values("market_cap", ascending=False)["ticker"]
        .dropna()
        .astype(str)
        .head(limit)
        .tolist()
    )
    return ", ".join(tickers) if tickers else "N/A"


def format_sector_bullets(frame: pd.DataFrame, include_trend: bool = False) -> str:
    if frame.empty:
        return "- N/A"
    lines: list[str] = []
    for _, row in frame.iterrows():
        trend = ""
        if include_trend:
            trend = f", YoY {fmt_signed_score(row.get('sector_health_trend_yoy'))}"
        lines.append(
            "- "
            f"{row.get('sector', 'N/A')}: Health {fmt_score(row.get('sector_health_score'))}"
            f"{trend}, {int(row.get('company_count', 0))} công ty,"
            f" {fmt_pct(row.get('market_cap_share'))} market cap,"
            f" cap-weighted Health {fmt_score(row.get('sector_cap_weighted_health'))},"
            f" top-cap {row.get('top_cap_tickers', 'N/A')}."
        )
    return "\n".join(lines)


def format_large_cap_bullets(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "- N/A"
    lines: list[str] = []
    for _, row in frame.iterrows():
        lines.append(
            "- "
            f"{row.get('ticker', 'N/A')} ({row.get('sector', 'N/A')}):"
            f" Health {fmt_score(row.get('corporate_health_score'))},"
            f" Growth {fmt_score(row.get('growth_score'))},"
            f" Cash Conversion {fmt_score(row.get('cash_conversion_score'))},"
            f" flag {row.get('primary_flag', 'N/A')}."
        )
    return "\n".join(lines)


def build_sector_leadership_context(
    current_sector: pd.DataFrame,
    current_company: pd.DataFrame,
    latest_vn100: pd.Series,
) -> dict[str, object]:
    sector = current_sector.copy()
    company = current_company.copy()
    company["market_cap"] = pd.to_numeric(company["market_cap"], errors="coerce")
    total_market_cap = company["market_cap"].sum()

    sector_rows: list[dict[str, object]] = []
    for sector_name, group in company.groupby("sector", dropna=False):
        cap_sum = group["market_cap"].sum()
        sector_rows.append(
            {
                "sector": sector_name,
                "sector_market_cap": cap_sum,
                "market_cap_share": cap_sum / total_market_cap if total_market_cap else float("nan"),
                "sector_cap_weighted_health": cap_weighted_score(group),
                "top_cap_tickers": sector_ticker_list(group),
            }
        )

    sector_cap = pd.DataFrame(sector_rows)
    sector = sector.merge(sector_cap, on="sector", how="left")
    trend = pd.to_numeric(sector.get("sector_health_trend_yoy"), errors="coerce")
    sector["positive_sector"] = trend.gt(0)
    sector.loc[trend.isna(), "positive_sector"] = sector.loc[trend.isna(), "sector_health_score"].ge(50)

    top_health = sector.sort_values("sector_health_score", ascending=False).head(3)
    positive = sector[sector["positive_sector"]].sort_values(
        ["sector_health_trend_yoy", "sector_health_score"], ascending=False
    )
    largest_sectors = sector.sort_values("market_cap_share", ascending=False).head(3)

    large_caps = company.sort_values("market_cap", ascending=False).head(15)
    large_cap_confirmers = large_caps[large_caps["corporate_health_score"].ge(55)].head(8)
    large_cap_drags = large_caps[large_caps["corporate_health_score"].lt(45)].head(5)

    equal_health = to_float(latest_vn100.get("vn100_health_score"))
    cap_health = to_float(latest_vn100.get("vn100_health_score_market_cap_weighted"))
    cap_gap = cap_health - equal_health
    positive_count = int(latest_vn100.get("positive_sector_count", positive.shape[0]))
    valid_count = int(latest_vn100.get("valid_sector_count", sector["sector_health_score"].notna().sum()))
    diffusion = to_float(latest_vn100.get("sector_diffusion_score"))
    top_health_cap_share = top_health["market_cap_share"].sum()
    positive_cap_share = positive["market_cap_share"].sum()

    if cap_gap >= 5:
        size_read = "Big caps are clearly leading the aggregate score"
    elif cap_gap >= 1.5:
        size_read = "Big caps modestly support the aggregate score"
    elif cap_gap <= -1.5:
        size_read = "Smaller and mid-cap names are healthier than big caps"
    else:
        size_read = "No clear size leadership in the aggregate score"

    sector_names = ", ".join(top_health["sector"].astype(str).tolist()) or "N/A"
    positive_names = ", ".join(positive["sector"].astype(str).tolist()) or "N/A"
    largest_names = ", ".join(largest_sectors["sector"].astype(str).tolist()) or "N/A"

    leadership_read = (
        f"Sector diffusion is {fmt_pct(diffusion)} ({positive_count}/{valid_count} positive sectors). "
        f"Top sectors by current health are {sector_names}, but they represent only "
        f"{fmt_pct(top_health_cap_share)} of VN100 market cap. Positive YoY sector movers are {positive_names}."
    )
    big_cap_read = (
        f"{size_read}: market-cap weighted Health {fmt_score(cap_health)} vs equal-weighted "
        f"{fmt_score(equal_health)} ({fmt_signed_score(cap_gap)} pts). Largest cap exposure is {largest_names}; "
        f"therefore this is not a clean broad-sector expansion even though big caps give some support."
    )

    return {
        "sector_leadership_read": leadership_read,
        "big_cap_read": big_cap_read,
        "top_sector_leaders": format_sector_bullets(top_health, include_trend=True),
        "positive_sector_movers": format_sector_bullets(positive.head(5), include_trend=True),
        "large_cap_confirmers": format_large_cap_bullets(large_cap_confirmers),
        "large_cap_drags": format_large_cap_bullets(large_cap_drags),
        "market_cap_health_gap": fmt_signed_score(cap_gap),
        "top_sector_market_cap_share": fmt_pct(top_health_cap_share),
        "positive_sector_market_cap_share": fmt_pct(positive_cap_share),
    }


def latest_period(company_scores: pd.DataFrame) -> tuple[str, int]:
    latest_order = int(company_scores["period_order"].max())
    latest = company_scores[company_scores["period_order"].eq(latest_order)]
    return str(latest["period"].iloc[0]), latest_order


def previous_order(latest_order: int, mode: str) -> int:
    return latest_order - (4 if mode == "YoY" else 1)


def add_change(current: pd.DataFrame, full: pd.DataFrame, mode: str) -> pd.DataFrame:
    if current.empty:
        return current
    lag_order = previous_order(int(current["period_order"].iloc[0]), mode)
    previous = full[full["period_order"].eq(lag_order)][[
        "ticker",
        "corporate_health_score",
    ]].rename(columns={"corporate_health_score": "health_change_base"})
    out = current.merge(previous, on="ticker", how="left")
    out["health_change"] = out["corporate_health_score"] - out["health_change_base"]
    return out


def resolve_api_key(raw_key: str | None, provider: str) -> tuple[str | None, str | None]:
    load_project_env()
    raw_key = (raw_key or "").strip()
    if raw_key:
        return raw_key, "Using API key from sidebar."

    cfg = AI_PROVIDER_MAP.get(provider, {})
    for env_name in cfg.get("env_keys", []):
        value = os.getenv(env_name, "").strip()
        if value:
            return value, f"Using API key from {env_name}."

    fallback = os.getenv("VN100_AI_API_KEY", "").strip()
    if fallback:
        return fallback, "Using API key from VN100_AI_API_KEY."

    return None, None


def first_provider_with_key() -> str:
    load_project_env()
    for provider in AI_PROVIDER_MAP:
        key, _ = resolve_api_key(None, provider)
        if key:
            return provider
    return next(iter(AI_PROVIDER_MAP))


def cache_path(provider: str, mode: str, period: str) -> Path:
    today_key = date.today().strftime("%d%m%y")
    mode_key = str(mode or "yoy").lower()
    return AI_CACHE_DIR / f"vn100_earnings_health_{provider}_{mode_key}_{today_key}.txt"


def list_cached_reports() -> list[Path]:
    if not AI_CACHE_DIR.exists():
        return []
    return sorted(
        AI_CACHE_DIR.glob("vn100_earnings_health_*.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def build_macro_verdict(latest_vn100: pd.Series) -> dict[str, object]:
    health = to_float(latest_vn100.get("vn100_health_score"))
    market_cap_health = to_float(latest_vn100.get("vn100_health_score_market_cap_weighted"))
    revenue = to_float(latest_vn100.get("revenue_breadth"))
    profit = to_float(latest_vn100.get("profit_breadth"))
    cfo = to_float(latest_vn100.get("cfo_breadth"))
    healthy = to_float(latest_vn100.get("healthy_growth_breadth"))
    wc_stress = to_float(latest_vn100.get("working_capital_stress_index"))
    leverage_stress = to_float(latest_vn100.get("leverage_stress_index"))
    diffusion = to_float(latest_vn100.get("sector_diffusion_score"))

    accounting_recovery = revenue >= 0.65 and profit >= 0.60
    cash_confirmed = cfo >= 0.60 and healthy >= 0.40
    broad_diffusion = diffusion >= 0.40
    stress_contained = wc_stress < 60 and leverage_stress < 60

    if health < 35 or wc_stress >= 70 or leverage_stress >= 70:
        verdict = "Stress"
        macro_read = "Sức khỏe doanh nghiệp đang ở trạng thái stress, cần ưu tiên rủi ro bảng cân đối và dòng tiền."
        stance = "Risk-focused"
    elif health >= 65 and accounting_recovery and cash_confirmed and broad_diffusion and stress_contained:
        verdict = "Broad Expansion"
        macro_read = "Sức khỏe doanh nghiệp đang mở rộng thật, được xác nhận đồng thời bởi tăng trưởng, dòng tiền và độ lan tỏa ngành."
        stance = "Constructive"
    elif health >= 55 and accounting_recovery and cash_confirmed and stress_contained:
        verdict = "Healthy Recovery"
        macro_read = "Nền doanh nghiệp đang phục hồi tương đối khỏe, nhưng vẫn cần kiểm tra độ lan tỏa ngành."
        stance = "Cautiously constructive"
    elif accounting_recovery and not cash_confirmed and stress_contained:
        verdict = "Accounting Recovery / Low Cash Confirmation"
        macro_read = "Doanh thu và lợi nhuận phục hồi rộng, nhưng dòng tiền và healthy growth chưa xác nhận nên chưa thể gọi là phục hồi khỏe."
        stance = "Selective / quality-focused"
    elif health >= 45 and stress_contained:
        verdict = "Mixed / Divergent"
        macro_read = "Sức khỏe tổng thể ở vùng trung tính, các tín hiệu phân hóa và chưa tạo được một pha mở rộng đồng bộ."
        stance = "Neutral / selective"
    else:
        verdict = "Weakening"
        macro_read = "Sức khỏe doanh nghiệp đang yếu đi, dù chưa nhất thiết đã thành stress hệ thống."
        stance = "Defensive"

    if accounting_recovery and cfo < revenue - 0.20:
        cash_quality = "Weak"
    elif cash_confirmed:
        cash_quality = "Healthy"
    else:
        cash_quality = "Mixed"

    if diffusion < 0.25:
        diffusion_read = "Very narrow"
    elif diffusion < 0.40:
        diffusion_read = "Narrow"
    elif diffusion < 0.60:
        diffusion_read = "Moderate"
    else:
        diffusion_read = "Broad"

    if max(wc_stress, leverage_stress) >= 60:
        stress_read = "Elevated"
    elif max(wc_stress, leverage_stress) >= 50:
        stress_read = "Watch"
    else:
        stress_read = "Contained"

    confidence_points = 0
    confidence_points += int(not pd.isna(health))
    confidence_points += int(not pd.isna(cfo))
    confidence_points += int(not pd.isna(healthy))
    confidence_points += int(not pd.isna(diffusion))
    confidence_points += int(not pd.isna(wc_stress) and not pd.isna(leverage_stress))
    confidence = "High" if confidence_points >= 5 else "Medium" if confidence_points >= 3 else "Low"

    evidence = [
        f"VN100 Health Score {fmt_score(health)} vs market-cap weighted {fmt_score(market_cap_health)}.",
        f"Revenue Breadth {fmt_pct(revenue)} và Profit Breadth {fmt_pct(profit)} cho thấy phục hồi kế toán khá rộng.",
        f"CFO Breadth {fmt_pct(cfo)} và Healthy Growth Breadth {fmt_pct(healthy)} cho thấy dòng tiền chưa xác nhận đầy đủ.",
        f"Sector Diffusion {fmt_pct(diffusion)} cho thấy sức khỏe chưa lan rộng giữa các ngành.",
        f"Working Capital Stress {fmt_score(wc_stress)} và Leverage Stress {fmt_score(leverage_stress)} hiện chưa báo stress hệ thống.",
    ]
    watch_next = [
        "CFO Breadth cần vượt vùng 60-65% để xác nhận lợi nhuận chuyển hóa tốt hơn thành tiền.",
        "Healthy Growth Breadth cần vượt 40% để nâng verdict từ phục hồi kế toán sang phục hồi khỏe hơn.",
        "Sector Diffusion cần phục hồi lên trên 35-40% để xác nhận sức khỏe lan rộng thay vì tập trung hẹp.",
        "Working Capital Stress và Leverage Stress cần duy trì dưới 60; vượt vùng này sẽ chuyển trọng tâm sang rủi ro bảng cân đối.",
        "Nếu Revenue/Profit Breadth vẫn cao nhưng CFO Breadth và Healthy Growth không cải thiện, verdict nên giữ ở Low Cash Confirmation.",
    ]

    return {
        "verdict": verdict,
        "macro_read": macro_read,
        "analytical_stance": stance,
        "confidence": confidence,
        "accounting_recovery": "Strong" if accounting_recovery else "Weak / mixed",
        "cash_confirmed_recovery": cash_quality,
        "sector_diffusion_read": diffusion_read,
        "systemic_stress_read": stress_read,
        "evidence": evidence,
        "watch_next": watch_next,
    }


def fill_prompt_template(template: str, payload: dict[str, object]) -> str:
    output = template
    for key, value in payload.items():
        output = output.replace(f"[{key}]", str(value))
    return output


def prepare_ai_payload(outputs: dict[str, pd.DataFrame], mode: str = "QoQ") -> dict[str, object]:
    company = outputs["company"].copy()
    sector = outputs["sector"].copy()
    vn100 = outputs["vn100"].copy()
    core_matrix = outputs["core_matrix"].copy()
    transmission = outputs["transmission"].copy()
    pca = outputs["pca"].copy()
    alerts = outputs["alerts"].copy()

    period, latest_order = latest_period(company)
    lag_order = previous_order(latest_order, mode)

    current_company = company[company["period_order"].eq(latest_order)].copy()
    current_company = add_change(current_company, company, mode)
    current_sector = sector[sector["period_order"].eq(latest_order)].copy()
    current_vn100 = vn100[vn100["period_order"].eq(latest_order)].tail(1)
    if current_vn100.empty:
        raise ValueError("VN100 latest score is not available.")
    latest_vn100 = current_vn100.iloc[0]

    vn100_trend = vn100[vn100["period_order"].le(latest_order)].tail(6)[[
        "period",
        "vn100_health_score",
        "regime",
        "revenue_breadth",
        "profit_breadth",
        "cfo_breadth",
        "healthy_growth_breadth",
        "working_capital_stress_index",
        "leverage_stress_index",
        "sector_diffusion_score",
    ]].copy()

    sector_table = current_sector[[
        "sector",
        "company_count",
        "sector_health_score",
        "sector_growth_score",
        "sector_cash_conversion_score",
        "sector_working_capital_stress",
        "sector_leverage_stress",
        "sector_diffusion_label",
    ]].sort_values("sector_health_score", ascending=False)

    top_companies = current_company[[
        "ticker",
        "company_name",
        "sector",
        "corporate_health_score",
        "health_change",
        "growth_score",
        "cash_conversion_score",
        "working_capital_stress_score",
        "leverage_stress_score",
        "primary_flag",
    ]].sort_values("corporate_health_score", ascending=False)

    bottom_companies = top_companies.sort_values("corporate_health_score", ascending=True)
    improving_companies = top_companies.dropna(subset=["health_change"]).sort_values("health_change", ascending=False)
    deteriorating_companies = top_companies.dropna(subset=["health_change"]).sort_values("health_change", ascending=True)

    matrix_diag = core_matrix[
        (core_matrix["period_order"].eq(latest_order))
        & (core_matrix["left_core"] != core_matrix["right_core"])
        & (core_matrix["severity"].isin(["High", "Medium"]))
    ][[
        "left_core",
        "right_core",
        "correlation",
        "diagnostic_label",
        "severity",
    ]].sort_values(["severity", "correlation"])

    broken_links = transmission[
        (transmission["period_order"].eq(latest_order))
        & (transmission["status"].isin(["broken", "weak"]))
    ].groupby(["link", "status"], as_index=False).agg(
        ticker_count=("ticker", "nunique"),
        avg_score=("score", "mean"),
    ).sort_values(["status", "ticker_count"], ascending=[True, False])

    alert_table = alerts.drop(columns=["period"], errors="ignore").head(15)

    pca_latest = pca[pca["period_order"].eq(latest_order)].tail(1)
    pca_row = pca_latest.iloc[0] if not pca_latest.empty else pd.Series(dtype=object)

    diagnosis = latest_vn100.get("main_diagnosis", "[]")
    if isinstance(diagnosis, str):
        try:
            diagnosis = json.loads(diagnosis)
        except Exception:
            diagnosis = [diagnosis]
    verdict_details = build_macro_verdict(latest_vn100)
    leadership_details = build_sector_leadership_context(current_sector, current_company, latest_vn100)

    payload = {
        "mode": mode,
        "period": period,
        "comparison_lag_order": lag_order,
        "final_verdict": verdict_details["verdict"],
        "final_macro_read": verdict_details["macro_read"],
        "final_stance": verdict_details["analytical_stance"],
        "final_confidence": verdict_details["confidence"],
        "accounting_recovery_read": verdict_details["accounting_recovery"],
        "cash_confirmed_recovery_read": verdict_details["cash_confirmed_recovery"],
        "sector_diffusion_read": verdict_details["sector_diffusion_read"],
        "systemic_stress_read": verdict_details["systemic_stress_read"],
        "sector_leadership_read": leadership_details["sector_leadership_read"],
        "big_cap_read": leadership_details["big_cap_read"],
        "top_sector_leaders": leadership_details["top_sector_leaders"],
        "positive_sector_movers": leadership_details["positive_sector_movers"],
        "large_cap_confirmers": leadership_details["large_cap_confirmers"],
        "large_cap_drags": leadership_details["large_cap_drags"],
        "market_cap_health_gap": leadership_details["market_cap_health_gap"],
        "top_sector_market_cap_share": leadership_details["top_sector_market_cap_share"],
        "positive_sector_market_cap_share": leadership_details["positive_sector_market_cap_share"],
        "final_evidence": "\n".join(f"- {item}" for item in verdict_details["evidence"]),
        "watch_next": "\n".join(f"- {item}" for item in verdict_details["watch_next"]),
        "vn100_health_score": fmt_score(latest_vn100.get("vn100_health_score")),
        "vn100_health_score_market_cap_weighted": fmt_score(latest_vn100.get("vn100_health_score_market_cap_weighted")),
        "positive_sector_count": int(latest_vn100.get("positive_sector_count", 0)),
        "valid_sector_count": int(latest_vn100.get("valid_sector_count", 0)),
        "regime": latest_vn100.get("regime", "N/A"),
        "valid_company_count": int(latest_vn100.get("valid_company_count", 0)),
        "revenue_breadth": fmt_pct(latest_vn100.get("revenue_breadth")),
        "profit_breadth": fmt_pct(latest_vn100.get("profit_breadth")),
        "cfo_breadth": fmt_pct(latest_vn100.get("cfo_breadth")),
        "healthy_growth_breadth": fmt_pct(latest_vn100.get("healthy_growth_breadth")),
        "working_capital_stress_index": fmt_score(latest_vn100.get("working_capital_stress_index")),
        "leverage_stress_index": fmt_score(latest_vn100.get("leverage_stress_index")),
        "sector_diffusion_score": fmt_pct(latest_vn100.get("sector_diffusion_score")),
        "main_diagnosis": "\n".join(f"- {item}" for item in diagnosis),
        "vn100_trend_table": frame_to_markdown(vn100_trend),
        "sector_table": frame_to_markdown(sector_table, max_rows=20),
        "top_company_table": frame_to_markdown(top_companies, max_rows=10),
        "bottom_company_table": frame_to_markdown(bottom_companies, max_rows=10),
        "improving_company_table": frame_to_markdown(improving_companies, max_rows=10),
        "deteriorating_company_table": frame_to_markdown(deteriorating_companies, max_rows=10),
        "matrix_diagnostics_table": frame_to_markdown(matrix_diag, max_rows=15),
        "transmission_breakdown_table": frame_to_markdown(broken_links, max_rows=15),
        "alerts_table": frame_to_markdown(alert_table, max_rows=15),
        "pca_common_health_factor": fmt_score(pca_row.get("common_health_factor"), digits=3),
        "pca_explained_variance": fmt_pct(pca_row.get("explained_variance_ratio")),
    }
    return payload


def build_prompt(outputs: dict[str, pd.DataFrame], mode: str) -> tuple[str, str, dict[str, object]]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_PATH}")
    payload = prepare_ai_payload(outputs, mode)
    full_prompt = fill_prompt_template(PROMPT_PATH.read_text(encoding="utf-8"), payload)
    parts = full_prompt.split("# INPUT DATA", maxsplit=1)
    if len(parts) == 2:
        system_prompt = parts[0].strip()
        user_prompt = "# INPUT DATA\n" + parts[1].strip()
    else:
        system_prompt = "You are a rigorous financial analyst."
        user_prompt = full_prompt
    return system_prompt, user_prompt, payload


def run_ai_analysis(
    outputs: dict[str, pd.DataFrame],
    *,
    provider: str,
    api_key: str,
    mode: str,
) -> tuple[str, Path]:
    from openai import OpenAI

    cfg = AI_PROVIDER_MAP[provider]
    system_prompt, user_prompt, payload = build_prompt(outputs, mode)
    period = str(payload["period"])
    target_cache = cache_path(provider, mode, period)

    client = OpenAI(
        api_key=api_key.strip(),
        base_url=cfg["base_url"],
        timeout=cfg.get("timeout", 180),
    )
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **completion_options(
            model=cfg["api_model"],
            route="child_report",
            temperature=cfg.get("temperature", AI_TEMPERATURE),
        ),
    )
    result = response.choices[0].message.content or ""
    target_cache.parent.mkdir(parents=True, exist_ok=True)
    target_cache.write_text(encode_vn100_ai_cache(result), encoding="utf-8")
    return result, target_cache
