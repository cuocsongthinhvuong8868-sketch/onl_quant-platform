from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from config import AI_PROVIDER_MAP, DATA_LAKE
from shared.data_loader import load_close_prices, load_custom, load_volumes


REPORT_GLOB = "executive_summary_{provider}_*.txt"
RESULT_CACHE_PREFIX = "humility_falsification"
FALSIFICATION_CUTOFF = 3

OPS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda left, right: left < right,
    ">": lambda left, right: left > right,
    "<=": lambda left, right: left <= right,
    ">=": lambda left, right: left >= right,
}

DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "model": "VNIBOR Monitor",
        "metric": "STRESS/WARNING sessions (20D)",
        "threshold_operator": "<",
        "threshold_value": 5,
        "unit": "sessions",
        "description": "Liquidity pressure is no longer persistent if stressed funding sessions fall below 5 of the last 20 observations.",
    },
    {
        "model": "Market Breadth",
        "metric": "Breadth MA20",
        "threshold_operator": ">",
        "threshold_value": 45,
        "unit": "%",
        "description": "Internal participation materially improves when more than 45% of covered tickers trade above MA20.",
    },
    {
        "model": "ESR Monitor",
        "metric": "Systemic Stress Index (SSI)",
        "threshold_operator": "<",
        "threshold_value": 55,
        "unit": "%",
        "description": "Systemic stress cools if SSI drops below 55%.",
    },
    {
        "model": "Tail Risk (EVT)",
        "metric": "Tail Index (xi)",
        "threshold_operator": "<",
        "threshold_value": 0.25,
        "unit": "",
        "description": "Left-tail risk normalizes when the EVT tail index falls below 0.25.",
    },
    {
        "model": "Manipulation / Coupling",
        "metric": "Vingroup Slope Percentile",
        "threshold_operator": "<",
        "threshold_value": 70,
        "unit": "th pct",
        "description": "Index coupling risk eases when the Vingroup slope percentile falls below the 70th percentile.",
    },
    {
        "model": "Global Financial Conditions",
        "metric": "CQS Percentile",
        "threshold_operator": "<",
        "threshold_value": 80,
        "unit": "th pct",
        "description": "External credit-quality stress eases when CQS drops below the 80th percentile.",
    },
]


def render() -> None:
    st.title("Humility & Falsification Monitor")
    st.caption(
        "So sanh cac dieu kien falsification trong AI CIO report ngay T-1 voi du lieu cap nhat ngay T."
    )

    force_result = st.sidebar.button("Recompute result cache", width="stretch")

    if st.sidebar.button("Refresh cached metrics", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    with st.spinner("Dang tinh du lieu hien tai tu cac cong cu..."):
        current_metrics = _compute_current_metrics()

    t_data_date = _effective_t_data_date(current_metrics)
    if t_data_date is None:
        st.error("Khong xac dinh duoc ngay T tu du lieu hien tai cua cac cong cu.")
        _render_metric_quality(current_metrics, None)
        return

    reports_by_provider = _reports_by_provider()
    if not any(reports_by_provider.values()):
        st.warning("Chua tim thay bao cao AI CIO trong data_lake/daily_cache.")
        return

    provider_key = _provider_selector(reports_by_provider)
    report_path, target_report_date, report_match = _auto_tminus_report(
        reports_by_provider[provider_key],
        t_data_date,
    )
    if report_path is None:
        st.error(f"Khong tim thay AI CIO report cho T-1 = {target_report_date.isoformat()}.")
        _render_metric_quality(current_metrics, t_data_date)
        return

    _render_auto_report_note(report_path, target_report_date, report_match)

    with st.spinner("Dang tai hoac tinh ket qua falsification..."):
        payload = build_humility_falsification_payload(
            provider_key=provider_key,
            current_metrics=current_metrics,
            force=force_result,
        )

    if payload.get("error"):
        st.error(str(payload["error"]))
        _render_metric_quality(current_metrics, t_data_date)
        return

    if payload.get("cache_hit"):
        st.success(f"Dung cache ket qua cung ngay: {payload.get('cache_path')}")
    else:
        st.success(f"Da tinh moi va luu cache ket qua: {payload.get('cache_path')}")

    parsed = _cached_parsed_for_render(payload.get("parsed", {}))
    result_df = pd.DataFrame(payload.get("rows", []))
    falsified = int(payload.get("falsified", 0))
    available = int(payload.get("available", 0))
    total = int(payload.get("total", len(result_df)))
    status = (str(payload.get("status_label", "N/A")), str(payload.get("status_help", "")))

    _render_summary(
        parsed,
        report_path,
        target_report_date,
        t_data_date,
        status,
        falsified,
        total,
        available,
    )
    _render_rule_table(result_df)
    _render_metric_quality(payload.get("current_metrics", current_metrics), t_data_date)
    _render_source_context(parsed, report_path)


def build_humility_falsification_payload(
    provider_key: str = "deepseek-v4-pro",
    current_metrics: dict[str, dict[str, Any]] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build or load the same-day falsification result payload.

    Cache identity is provider + T data date + exact T-1 report path/mtime. That
    keeps the dashboard fast while still invalidating if the source AI CIO report
    for the same date is regenerated.
    """

    t_data_date = _effective_t_data_date(current_metrics) if current_metrics is not None else _latest_close_data_date()
    reports = _reports_by_provider().get(provider_key, [])

    if t_data_date is not None and reports:
        report_path, target_report_date, report_match = _auto_tminus_report(reports, t_data_date)
        if report_path is not None and not force:
            cache_path = _humility_cache_path(provider_key, t_data_date)
            report_mtime = _path_mtime(report_path)
            cached = _read_humility_cache(cache_path, provider_key, t_data_date, report_path, report_mtime)
            if cached:
                cached["cache_hit"] = True
                cached["cache_path"] = str(cache_path)
                return cached

    current_metrics = current_metrics or _compute_current_metrics_uncached()
    t_data_date = _effective_t_data_date(current_metrics)
    if t_data_date is None:
        return {
            "error": "Khong xac dinh duoc ngay T tu du lieu hien tai cua cac cong cu.",
            "current_metrics": current_metrics,
        }

    if not reports:
        return {
            "error": f"Chua tim thay AI CIO report cho provider {provider_key}.",
            "provider_key": provider_key,
            "t_data_date": t_data_date.isoformat(),
            "current_metrics": current_metrics,
        }

    report_path, target_report_date, report_match = _auto_tminus_report(reports, t_data_date)
    if report_path is None:
        return {
            "error": f"Khong tim thay AI CIO report cho T-1 = {target_report_date.isoformat()}.",
            "provider_key": provider_key,
            "t_data_date": t_data_date.isoformat(),
            "target_report_date": target_report_date.isoformat(),
            "report_match": report_match,
            "current_metrics": current_metrics,
        }

    cache_path = _humility_cache_path(provider_key, t_data_date)
    report_mtime = _path_mtime(report_path)

    parsed = _load_report_rules(report_path)
    rows = [_evaluate_rule(rule, current_metrics) for rule in parsed["rules"]]
    result_df = pd.DataFrame(rows)
    falsified = int(result_df["Falsified"].sum()) if not result_df.empty else 0
    available = int(result_df["T actual"].notna().sum()) if not result_df.empty else 0
    total = len(result_df)
    status_label, status_help = _thesis_status(falsified)

    payload = _json_ready(
        {
            "provider_key": provider_key,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "t_data_date": t_data_date.isoformat(),
            "target_report_date": target_report_date.isoformat(),
            "report_match": report_match,
            "report_path": str(report_path),
            "report_mtime": report_mtime,
            "parsed": _parsed_for_cache(parsed),
            "rows": rows,
            "current_metrics": current_metrics,
            "status_label": status_label,
            "status_help": status_help,
            "falsified": falsified,
            "available": available,
            "total": total,
        }
    )
    _write_humility_cache(cache_path, payload)
    payload["cache_hit"] = False
    payload["cache_path"] = str(cache_path)
    return payload


def get_humility_falsification_context(provider_key: str = "deepseek-v4-pro", force: bool = False) -> str:
    """Return a compact markdown context block for AI CIO synthesis."""

    payload = build_humility_falsification_payload(provider_key=provider_key, force=force)
    return format_humility_payload_markdown(payload)


def format_humility_payload_markdown(payload: dict[str, Any]) -> str:
    if payload.get("error"):
        return f"DATA INSUFFICIENT - Humility & Falsification Monitor: {payload['error']}"

    lines = [
        f"- Provider: {payload.get('provider_key', 'N/A')}",
        f"- T data date: {payload.get('t_data_date', 'N/A')}",
        f"- AI CIO report checked: {Path(str(payload.get('report_path', ''))).name}",
        f"- Report match: {payload.get('report_match', 'N/A')}",
        f"- Thesis status: {payload.get('status_label', 'N/A')}",
        f"- Rules triggered: {payload.get('falsified', 0)}/{payload.get('total', 0)}",
        f"- Available T metrics: {payload.get('available', 0)}/{payload.get('total', 0)}",
        f"- Cache: {'HIT' if payload.get('cache_hit') else 'REFRESHED'} ({payload.get('cache_path', 'N/A')})",
        "",
        "| Model | Metric | Threshold | T-1 reported | T actual | Delta | Status | Data date |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in payload.get("rows", []):
        lines.append(
            "| {model} | {metric} | {threshold} | {tminus} | {actual} | {delta} | {status} | {date} |".format(
                model=_md_cell(row.get("Model", "")),
                metric=_md_cell(row.get("Metric", "")),
                threshold=_md_cell(row.get("T-1 threshold", "")),
                tminus=_md_cell(row.get("T-1 reported", "")),
                actual=_md_cell(row.get("T actual display", "")),
                delta=_md_cell(row.get("Delta display", "")),
                status=_md_cell(row.get("Status", "")),
                date=_md_cell(row.get("Data date", "")),
            )
        )

    errors = [
        f"- {key}: {value.get('error')}"
        for key, value in payload.get("current_metrics", {}).items()
        if value.get("error")
    ]
    if errors:
        lines.extend(["", "Metric quality warnings:", *errors])
    return "\n".join(lines)


def _humility_cache_path(provider_key: str, t_data_date: date) -> Path:
    date_key = t_data_date.strftime("%d%m%y")
    return DATA_LAKE / "daily_cache" / f"{RESULT_CACHE_PREFIX}_{provider_key}_{date_key}.json"


def _latest_close_data_date() -> date | None:
    path = DATA_LAKE / "market_data.csv"
    if not path.exists():
        return None
    try:
        date_col = pd.read_csv(path, usecols=[0], parse_dates=[0]).iloc[:, 0]
        return pd.Timestamp(date_col.dropna().iloc[-1]).date()
    except Exception:
        return None


def _path_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def _read_humility_cache(
    cache_path: Path,
    provider_key: str,
    t_data_date: date,
    report_path: Path,
    report_mtime: str,
) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if payload.get("provider_key") != provider_key:
        return None
    if payload.get("t_data_date") != t_data_date.isoformat():
        return None
    if payload.get("report_path") != str(report_path):
        return None
    if payload.get("report_mtime") != report_mtime:
        return None
    return payload


def _write_humility_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parsed_for_cache(parsed: dict[str, Any]) -> dict[str, Any]:
    cached = dict(parsed)
    report_date = cached.get("report_date")
    if isinstance(report_date, date):
        cached["report_date"] = report_date.isoformat()
    return _json_ready(cached)


def _cached_parsed_for_render(parsed: dict[str, Any]) -> dict[str, Any]:
    rendered = dict(parsed)
    rendered["report_date"] = _payload_date(rendered.get("report_date"))
    return rendered


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_ready(child) for child in value]
    if isinstance(value, tuple):
        return [_json_ready(child) for child in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value) and not isinstance(value, (str, bytes)):
            return None
    except Exception:
        pass
    return value


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ").strip()


def _provider_selector(reports_by_provider: dict[str, list[Path]]) -> str:
    available_keys = [key for key, paths in reports_by_provider.items() if paths]
    preferred = next((key for key in ("deepseek-v4-pro", "kimi-2.6") if key in available_keys), available_keys[0])
    labels = {
        key: f"{_provider_display_name(key)} ({len(reports_by_provider[key])})"
        for key in available_keys
    }

    return st.sidebar.selectbox(
        "AI CIO provider",
        available_keys,
        index=available_keys.index(preferred),
        format_func=lambda key: labels[key],
    )


def _reports_by_provider() -> dict[str, list[Path]]:
    daily_cache = DATA_LAKE / "daily_cache"
    reports: dict[str, list[Path]] = {}
    for provider_key in AI_PROVIDER_MAP:
        paths = sorted(
            daily_cache.glob(REPORT_GLOB.format(provider=provider_key)),
            key=lambda path: (_date_from_report_path(path) or date.min, path.name),
            reverse=True,
        )
        reports[provider_key] = paths
    return reports


def _provider_display_name(provider_key: str) -> str:
    provider_meta = AI_PROVIDER_MAP.get(provider_key, {})
    if isinstance(provider_meta, dict):
        return str(provider_meta.get("display") or provider_key)
    return str(provider_meta or provider_key)


def _auto_tminus_report(paths: list[Path], t_data_date: date) -> tuple[Path | None, date, str]:
    target_date = t_data_date - timedelta(days=1)
    dated_paths = [
        (report_date, path)
        for path in paths
        if (report_date := _date_from_report_path(path)) is not None
    ]
    for report_date, path in dated_paths:
        if report_date == target_date:
            return path, target_date, "exact"

    prior_reports = [(report_date, path) for report_date, path in dated_paths if report_date < target_date]
    if prior_reports:
        report_date, path = max(prior_reports, key=lambda item: item[0])
        return path, target_date, f"fallback:{report_date.isoformat()}"
    return None, target_date, "missing"


def _render_auto_report_note(report_path: Path, target_report_date: date, report_match: str) -> None:
    report_date = _date_from_report_path(report_path)
    if report_match == "exact":
        st.sidebar.success(
            f"Auto T-1 report: {target_report_date.isoformat()}\n\n{report_path.name}"
        )
        return

    used_date = report_date.isoformat() if report_date else "unknown"
    st.sidebar.warning(
        f"Khong co report dung T-1 = {target_report_date.isoformat()}. "
        f"Dang dung report gan nhat truoc do: {used_date}."
    )


def _load_report_rules(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    payload = _extract_falsification_json(text)
    if payload:
        rules = _rules_from_payload(payload)
        if rules:
            return {
                "report_date": _payload_date(payload.get("report_date")) or _date_from_report_path(path),
                "composite_score": _as_float(payload.get("composite_score")),
                "regime": payload.get("regime") or _parse_regime(text),
                "rules": rules,
                "parse_mode": "structured JSON",
                "raw_payload": payload,
            }

    rules = _fallback_rules_from_text(text)
    return {
        "report_date": _date_from_report_path(path),
        "composite_score": _parse_score(text),
        "regime": _parse_regime(text),
        "rules": rules,
        "parse_mode": "markdown fallback",
        "raw_payload": None,
    }


def _extract_falsification_json(text: str) -> dict[str, Any] | None:
    marker = '"falsification_rules"'
    idx = text.find(marker)
    if idx < 0:
        return None

    for start in reversed([match.start() for match in re.finditer(r"\{", text[:idx])]):
        candidate = _balanced_json(text, start)
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("falsification_rules"), list):
            return payload
    return None


def _balanced_json(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False

    for pos in range(start, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
    return None


def _rules_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for item in payload.get("falsification_rules", []):
        if not isinstance(item, dict):
            continue
        op = str(item.get("threshold_operator", "")).strip()
        threshold = _as_float(item.get("threshold_value"))
        if op not in OPS or threshold is None:
            continue
        rules.append(
            {
                "model": str(item.get("model", "")).strip() or "Unknown model",
                "metric": str(item.get("metric", "")).strip() or "Unknown metric",
                "threshold_operator": op,
                "threshold_value": threshold,
                "current_value": _as_float(item.get("current_value")),
                "unit": str(item.get("unit", "")).strip(),
                "description": str(item.get("description", "")).strip(),
            }
        )
    return rules


def _fallback_rules_from_text(text: str) -> list[dict[str, Any]]:
    tminus_values = _extract_tminus_values(_extract_humility_section(text))
    if "vnibor" not in tminus_values:
        tminus_values.update({k: v for k, v in _extract_tminus_values(text).items() if k == "vnibor"})
    rules: list[dict[str, Any]] = []
    for default_rule in DEFAULT_RULES:
        rule = dict(default_rule)
        rule["current_value"] = tminus_values.get(_metric_key(rule))
        rules.append(rule)
    return rules


def _extract_humility_section(text: str) -> str:
    match = re.search(r"##\s*8\.\s*Model Humility Box", text, flags=re.IGNORECASE)
    if not match:
        return text
    tail = text[match.start() :]
    final_line = re.search(r"final score\s*&\s*regime", tail, flags=re.IGNORECASE)
    return tail[: final_line.start()] if final_line else tail


def _extract_tminus_values(text: str) -> dict[str, float]:
    patterns: dict[str, tuple[str, str]] = {
        "vnibor": (r"VNIBOR", r"(\d+(?:\.\d+)?)\s*/\s*20\s*phi[eê]n\s+STRESS"),
        "breadth": (r"Breadth MA20|m[aã]\s+tr[eê]n\s+MA20", r"t[uừ]\s+(\d+(?:\.\d+)?)%"),
        "ssi": (r"\bSSI\b|ESR SSI", r"t[uừ]\s+(\d+(?:\.\d+)?)%"),
        "evt": (r"EVT|tail-index|tail index|ξ", r"t[uừ]\s+(\d+(?:\.\d+)?)"),
        "coupling": (r"Coupling|Slope percentile|Vingroup", r"t[uừ]\s+(\d+(?:\.\d+)?)th"),
        "gfc": (r"Global Financial Conditions|CQS", r"t[uừ]\s+(\d+(?:\.\d+)?)th"),
    }
    values: dict[str, float] = {}
    for line in text.splitlines():
        for key, (line_pattern, value_pattern) in patterns.items():
            if key in values or not re.search(line_pattern, line, flags=re.IGNORECASE):
                continue
            match = re.search(value_pattern, line, flags=re.IGNORECASE)
            if match:
                values[key] = float(match.group(1))
    return values


def _compute_current_metrics() -> dict[str, dict[str, Any]]:
    return _compute_current_metrics_uncached()


def _compute_current_metrics_uncached() -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    df_close: pd.DataFrame | None = None
    try:
        df_close = load_close_prices()
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        metrics["market_data"] = _metric(error=f"Khong doc duoc close prices: {exc}")

    metrics["vnibor"] = _current_vnibor()
    metrics["breadth"] = _current_breadth(df_close)
    metrics["ssi"] = _current_esr_ssi(df_close)
    metrics["evt"] = _current_evt_tail_index()
    metrics["coupling"] = _current_vingroup_coupling(df_close)
    metrics["gfc"] = _current_gfc_cqs()
    return metrics


def _current_vnibor() -> dict[str, Any]:
    try:
        from tools.vnibor.quant.metrics import load_vnibor_data, process_vnibor_logic

        df_vnibor = process_vnibor_logic(load_vnibor_data())
        if df_vnibor.empty or "Signal" not in df_vnibor:
            return _metric(error="VNIBOR data khong co cot Signal.")

        recent = df_vnibor.tail(20)
        value = int(recent["Signal"].isin(["STRESS", "WARNING"]).sum())
        return _metric(value=value, data_date=_last_index_date(recent))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _current_breadth(df_close: pd.DataFrame | None) -> dict[str, Any]:
    try:
        if df_close is None or df_close.empty:
            return _metric(error="Close prices rong.")
        from tools.market_breadth.quant.metrics import compute_breadth

        _, masks = compute_breadth(df_close)
        mask = masks.get("> MA20")
        if mask is None or mask.empty:
            return _metric(error="Khong tinh duoc mask > MA20.")
        latest = mask.dropna(how="all").iloc[-1]
        value = float(latest.sum() / latest.count() * 100)
        return _metric(value=value, data_date=_last_index_date(mask.dropna(how="all")))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _current_esr_ssi(df_close: pd.DataFrame | None) -> dict[str, Any]:
    try:
        if df_close is None or df_close.empty:
            return _metric(error="Close prices rong.")
        from tools.esr_monitor.quant.metrics import PRODUCTION_REGIME_METHOD, run_esr_pipeline

        df_vn30 = load_custom("vn30_cache.csv")
        df_volume = load_volumes()
        _, result, _, _ = run_esr_pipeline(
            df_close,
            df_vn30=df_vn30,
            df_volume=df_volume,
            deposit_rate=0.06,
            pillar_mode="downside",
            pca_warmup=252,
            ema_span=20,
            regime_method=PRODUCTION_REGIME_METHOD,
        )
        ssi = result.ssi.dropna()
        if ssi.empty:
            return _metric(error="ESR SSI rong.")
        return _metric(value=float(ssi.iloc[-1] * 100), data_date=_last_index_date(ssi))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _current_evt_tail_index() -> dict[str, Any]:
    try:
        from tools.var_cvar_vnindex.quant.metrics import calculate_var_cvar_metrics

        df_vnindex = load_custom("vnindex_cache.csv")
        series = _first_numeric_series(df_vnindex, preferred=("VNINDEX", "close", "Close"))
        metrics = calculate_var_cvar_metrics(series, include_evt=True)
        xi = metrics.get("evt_xi")
        if xi is None:
            return _metric(error="EVT xi khong co trong ket qua VaR/CVaR.")
        xi = xi.dropna()
        if xi.empty:
            return _metric(error="EVT xi rong.")
        return _metric(value=float(xi.iloc[-1]), data_date=_last_index_date(xi))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _current_vingroup_coupling(df_close: pd.DataFrame | None) -> dict[str, Any]:
    try:
        if df_close is None or df_close.empty:
            return _metric(error="Close prices rong.")
        from tools.manipulation.quant.engine import compute_metrics, prepare_data

        prices = prepare_data(df_close)
        _, result_df = compute_metrics(prices, window=60)
        series = result_df["PR_Slope"].dropna()
        if series.empty:
            return _metric(error="PR_Slope rong.")
        return _metric(value=float(series.iloc[-1] * 100), data_date=_last_index_date(series))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _current_gfc_cqs() -> dict[str, Any]:
    try:
        from tools.global_financial_conditions.quant.metrics import load_cached_gfcm

        df_gfcm = load_cached_gfcm(DATA_LAKE / "global_financial_conditions_cache.csv")
        clean = df_gfcm.dropna(subset=["CQS_pct"])
        if clean.empty:
            return _metric(error="CQS_pct rong.")
        return _metric(value=float(clean["CQS_pct"].iloc[-1] * 100), data_date=_last_index_date(clean))
    except Exception as exc:  # pragma: no cover - displayed in Streamlit
        return _metric(error=str(exc))


def _evaluate_rule(rule: dict[str, Any], current_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _metric_key(rule)
    metric = current_metrics.get(key, {})
    actual = _as_float(metric.get("value"))
    op = str(rule.get("threshold_operator", "")).strip()
    unit = str(rule.get("unit", "")).strip()
    threshold = _normalize_percent_like(_as_float(rule.get("threshold_value")), unit)

    falsified = bool(actual is not None and threshold is not None and op in OPS and OPS[op](actual, threshold))
    tminus = _normalize_percent_like(_as_float(rule.get("current_value")), unit)
    delta = actual - tminus if actual is not None and tminus is not None else None

    return {
        "Model": rule.get("model", ""),
        "Metric": rule.get("metric", ""),
        "T-1 threshold": _format_threshold(op, threshold, unit),
        "T-1 reported": _format_value(tminus, unit),
        "T actual": actual,
        "T actual display": _format_value(actual, unit),
        "Delta": delta,
        "Delta display": _format_delta(delta, unit),
        "Status": "FALSIFIED" if falsified else ("MISSING" if actual is None else "Intact"),
        "Data date": metric.get("date") or "",
        "Description": rule.get("description", ""),
        "Error": metric.get("error") or "",
        "Falsified": falsified,
    }


def _metric_key(rule: dict[str, Any]) -> str:
    haystack = f"{rule.get('model', '')} {rule.get('metric', '')}".lower()
    if "breadth" in haystack or "ma20" in haystack:
        return "breadth"
    if re.search(r"\bssi\b", haystack) or "esr" in haystack or "systemic" in haystack:
        return "ssi"
    if "evt" in haystack or "tail" in haystack or "xi" in haystack or "ξ" in haystack:
        return "evt"
    if "vingroup" in haystack or "coupling" in haystack or "slope" in haystack:
        return "coupling"
    if "cqs" in haystack or "global" in haystack or "financial conditions" in haystack:
        return "gfc"
    if "vnibor" in haystack or "sessions" in haystack or "phiên" in haystack:
        return "vnibor"
    return haystack.strip()


def _render_summary(
    parsed: dict[str, Any],
    report_path: Path,
    target_report_date: date,
    t_data_date: date,
    status: tuple[str, str],
    falsified: int,
    total: int,
    available: int,
) -> None:
    report_date = parsed.get("report_date")
    status_label, status_help = status

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("T data as of", t_data_date.isoformat())
    c2.metric("Auto T-1 report", report_date.isoformat() if isinstance(report_date, date) else report_path.name)
    c3.metric("Rules triggered", f"{falsified}/{total}")
    c4.metric("Thesis status", status_label)

    if isinstance(report_date, date) and report_date != target_report_date:
        st.warning(
            f"Target T-1 theo du lieu T la {target_report_date.isoformat()}, "
            f"nhung report dang dung la {report_date.isoformat()}."
        )

    score = parsed.get("composite_score")
    regime = parsed.get("regime") or "N/A"
    st.info(
        f"AI CIO report dung de doi chieu: score {score if score is not None else 'N/A'}, regime {regime}. "
        f"Available T metrics: {available}/{total}. {status_help}"
    )


def _render_rule_table(result_df: pd.DataFrame) -> None:
    st.subheader("Rule-by-rule falsification")
    if result_df.empty:
        st.warning("Khong co rule hop le de danh gia.")
        return

    display_df = result_df[
        [
            "Model",
            "Metric",
            "T-1 threshold",
            "T-1 reported",
            "T actual display",
            "Delta display",
            "Status",
            "Data date",
            "Description",
            "Error",
        ]
    ].rename(columns={"T actual display": "T actual", "Delta display": "Delta"})

    def style_row(row: pd.Series) -> list[str]:
        if row["Status"] == "FALSIFIED":
            return ["background-color: #ffe5e5"] * len(row)
        if row["Status"] == "MISSING":
            return ["background-color: #fff4d6"] * len(row)
        return ["background-color: #eaf7ef"] * len(row)

    st.dataframe(display_df.style.apply(style_row, axis=1), width="stretch", hide_index=True)

    status_counts = result_df["Status"].value_counts().rename_axis("Status").to_frame("Rules")
    st.bar_chart(status_counts)


def _render_metric_quality(current_metrics: dict[str, dict[str, Any]], t_data_date: date | None) -> None:
    metric_rows = []
    for key, value in current_metrics.items():
        metric_date = _parse_metric_date(value.get("date"))
        lag_days = (t_data_date - metric_date).days if t_data_date and metric_date else None
        metric_rows.append(
            {
                "Metric": key,
                "T data date": value.get("date", ""),
                "Lag vs T": lag_days,
                "Current value": value.get("value"),
                "Issue": value.get("error", ""),
            }
        )
    with st.expander("T data coverage by metric"):
        st.dataframe(pd.DataFrame(metric_rows), width="stretch", hide_index=True)

    errors = [
        {"Metric": key, "Issue": value.get("error", "")}
        for key, value in current_metrics.items()
        if value.get("error")
    ]
    if errors:
        with st.expander("Metric quality warnings", expanded=True):
            st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)


def _render_source_context(parsed: dict[str, Any], report_path: Path) -> None:
    with st.expander("Source and parser details"):
        st.write(f"Report: `{report_path}`")
        st.write(f"Parse mode: `{parsed.get('parse_mode')}`")
        if parsed.get("raw_payload") is not None:
            st.json(parsed["raw_payload"])
        else:
            st.caption(
                "Bao cao cu khong co JSON falsification block, dashboard dang dung bo 6 rule mac dinh va "
                "trich xuat gia tri T-1 tu Model Humility Box neu co."
            )


def _thesis_status(falsified: int) -> tuple[str, str]:
    if falsified >= FALSIFICATION_CUTOFF:
        return (
            "FALSIFIED",
            "Tu 3 rule tro len da bi kich hoat; baseline thesis cua AI CIO can duoc vo hieu hoa hoac viet lai.",
        )
    if falsified:
        return (
            "WATCH",
            "Mot so dieu kien da bi kich hoat, nhung chua du nguong 3/6 de falsify toan bo thesis.",
        )
    return (
        "INTACT",
        "Chua co dieu kien falsification nao bi kich hoat tren cac metric hien co.",
    )


def _effective_t_data_date(current_metrics: dict[str, dict[str, Any]]) -> date | None:
    dates = [
        parsed
        for metric in current_metrics.values()
        if (parsed := _parse_metric_date(metric.get("date"))) is not None
    ]
    return max(dates) if dates else None


def _parse_metric_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _metric(value: float | int | None = None, data_date: str | None = None, error: str = "") -> dict[str, Any]:
    return {"value": value, "date": data_date or "", "error": error}


def _first_numeric_series(df: pd.DataFrame, preferred: tuple[str, ...] = ()) -> pd.Series:
    for column in preferred:
        if column in df.columns:
            return pd.to_numeric(df[column], errors="coerce").dropna()
    numeric = df.select_dtypes(include="number")
    if numeric.empty:
        raise ValueError("DataFrame khong co cot numeric.")
    return pd.to_numeric(numeric.iloc[:, 0], errors="coerce").dropna()


def _last_index_date(obj: pd.DataFrame | pd.Series) -> str:
    if obj.empty:
        return ""
    value = obj.index[-1]
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return str(value)


def _date_from_report_path(path: Path) -> date | None:
    match = re.search(r"_(\d{6})$", path.stem)
    if not match:
        return None
    raw = match.group(1)
    try:
        return date(2000 + int(raw[4:6]), int(raw[2:4]), int(raw[:2]))
    except ValueError:
        return None


def _payload_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _parse_score(text: str) -> float | None:
    matches = re.findall(r"final score\s*&\s*regime\s*:\s*([-+]?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    return float(matches[-1]) if matches else None


def _parse_regime(text: str) -> str | None:
    matches = re.findall(
        r"final score\s*&\s*regime\s*:\s*[-+]?\d+(?:\.\d+)?\s*;\s*regime\s*:\s*([^\n`]+)",
        text,
        flags=re.IGNORECASE,
    )
    return matches[-1].strip(" .;") if matches else None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _normalize_percent_like(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    unit_l = unit.lower()
    is_percent_like = "%" in unit_l or "percentile" in unit_l or "pct" in unit_l or "th" in unit_l
    if is_percent_like and 0 <= abs(value) <= 1:
        return value * 100
    return value


def _format_threshold(op: str, threshold: float | None, unit: str) -> str:
    if threshold is None:
        return "N/A"
    return f"{op} {_format_number(threshold)}{_unit_suffix(unit)}"


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "N/A"
    return f"{_format_number(value)}{_unit_suffix(unit)}"


def _format_delta(value: float | None, unit: str) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{_format_number(value)}{_unit_suffix(unit)}"


def _format_number(value: float) -> str:
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _unit_suffix(unit: str) -> str:
    if not unit:
        return ""
    if unit == "%":
        return "%"
    return f" {unit}"
