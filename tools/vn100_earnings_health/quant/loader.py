from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_LAKE, ROOT_DIR


LOCAL_OUTPUT_DIR = Path("/Users/macos/Desktop/vn100_earning-health_monitor/outputs")
FALLBACK_OUTPUT_DIR = DATA_LAKE / "vn100_earnings_health" / "outputs"

TABLES = {
    "vn100": "vn100_composite",
    "sectors": "sector_scores",
    "tickers": "ticker_metrics",
    "csad": "csad_breadth",
    "pca": "pca_validation",
    "parse_log": "parse_log",
    "failed_parse_log": "failed_parse_log",
}


def _has_outputs(path: Path) -> bool:
    return (path / "vn100_composite.csv").exists() or (path / "vn100_composite.parquet").exists()


def resolve_output_dir() -> Path:
    """Resolve VN100 output folder.

    Priority:
    1. VN100_EARNINGS_HEALTH_OUTPUT_DIR env var
    2. Local standalone VN100 project on this Mac
    3. Frozen fallback copied into platform data_lake
    """
    env_dir = os.getenv("VN100_EARNINGS_HEALTH_OUTPUT_DIR", "").strip()
    candidates = [Path(env_dir)] if env_dir else []
    candidates.extend([LOCAL_OUTPUT_DIR, FALLBACK_OUTPUT_DIR])
    for candidate in candidates:
        if candidate and _has_outputs(candidate):
            return candidate
    return FALLBACK_OUTPUT_DIR


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "period_end_date" in df.columns:
        df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
    return df


def read_table(name: str, output_dir: Path | None = None) -> pd.DataFrame:
    output_dir = output_dir or resolve_output_dir()
    csv_path = output_dir / f"{name}.csv"
    parquet_path = output_dir / f"{name}.parquet"
    if csv_path.exists():
        return _read_csv(csv_path)
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    return pd.DataFrame()


def load_outputs(output_dir: Path | None = None) -> dict[str, pd.DataFrame | Path]:
    output_dir = output_dir or resolve_output_dir()
    outputs: dict[str, pd.DataFrame | Path] = {"output_dir": output_dir}
    for key, file_stem in TABLES.items():
        outputs[key] = read_table(file_stem, output_dir)
    return outputs


def load_universe_tickers(output_dir: Path | None = None, outputs: dict[str, Any] | None = None) -> list[str]:
    output_dir = output_dir or resolve_output_dir()
    candidates = [
        output_dir.parent / "config" / "vn100_universe.csv",
        LOCAL_OUTPUT_DIR.parent / "config" / "vn100_universe.csv",
        DATA_LAKE / "vn100_earnings_health" / "vn100_universe.csv",
        ROOT_DIR / "vn100_universe.csv",
    ]
    for path in candidates:
        if path.exists():
            universe = pd.read_csv(path)
            if "ticker" in universe.columns:
                return sorted(universe["ticker"].dropna().astype(str).str.upper().unique().tolist())

    if outputs:
        tickers = outputs.get("tickers")
        if isinstance(tickers, pd.DataFrame) and "ticker" in tickers.columns:
            return sorted(tickers["ticker"].dropna().astype(str).str.upper().unique().tolist())
    return []


def latest_valid(df: pd.DataFrame, score_col: str) -> pd.Series | None:
    if df.empty or score_col not in df.columns:
        return None
    valid = df.dropna(subset=[score_col])
    if valid.empty:
        return None
    return valid.iloc[-1]


def latest_period_rows(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty or "period" not in df.columns:
        return pd.DataFrame()
    return df[df["period"].astype(str) == str(period)].copy()


def fmt_num(value: Any, digits: int = 3, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "+" if signed else ""
    return f"{number:{sign}.{digits}f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        return f"{value:+.3f}" if value < 0 else f"{value:.3f}"
    return str(value)


def frame_to_markdown(df: pd.DataFrame, max_rows: int | None = None) -> str:
    if df.empty:
        return "N/A"
    if max_rows is not None:
        df = df.head(max_rows)

    columns = list(df.columns)
    rows = [
        "| " + " | ".join(str(col) for col in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in df.iterrows():
        values = [_format_cell(row[col]).replace("|", "/") for col in columns]
        rows.append("| " + " | ".join(values) + " |")
    return "\n" + "\n".join(rows)


def four_quarter_change(df: pd.DataFrame, column: str) -> str:
    if df.empty or column not in df.columns:
        return "N/A"
    valid = df.dropna(subset=[column])
    if len(valid) < 5:
        return "N/A"
    return fmt_num(float(valid.iloc[-1][column]) - float(valid.iloc[-5][column]), signed=True)


def _parsed_tickers(parse_log: pd.DataFrame) -> set[str]:
    if parse_log.empty or "ticker_detected" not in parse_log.columns:
        return set()
    if "parse_status" in parse_log.columns:
        parse_log = parse_log[parse_log["parse_status"].astype(str).str.lower() == "ok"]
    return set(parse_log["ticker_detected"].dropna().astype(str).str.upper())


def _failed_tickers(failed_parse_log: pd.DataFrame, parse_log: pd.DataFrame) -> list[str]:
    failed: set[str] = set()
    if not failed_parse_log.empty and "ticker" in failed_parse_log.columns:
        failed.update(failed_parse_log["ticker"].dropna().astype(str).str.upper())
    if not parse_log.empty and {"ticker_detected", "parse_status"}.issubset(parse_log.columns):
        bad = parse_log[parse_log["parse_status"].astype(str).str.lower().isin(["error", "failed"])]
        failed.update(bad["ticker_detected"].dropna().astype(str).str.upper())
    return sorted(failed)


def _period_end_display(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if value is None or pd.isna(value):
        return "N/A"
    return str(value)


def prepare_ai_payload(outputs: dict[str, Any]) -> dict[str, str]:
    vn100: pd.DataFrame = outputs.get("vn100", pd.DataFrame())
    sectors: pd.DataFrame = outputs.get("sectors", pd.DataFrame())
    tickers: pd.DataFrame = outputs.get("tickers", pd.DataFrame())
    csad: pd.DataFrame = outputs.get("csad", pd.DataFrame())
    pca: pd.DataFrame = outputs.get("pca", pd.DataFrame())
    parse_log: pd.DataFrame = outputs.get("parse_log", pd.DataFrame())
    failed_parse_log: pd.DataFrame = outputs.get("failed_parse_log", pd.DataFrame())
    output_dir: Path = outputs.get("output_dir", resolve_output_dir())

    latest = latest_valid(vn100, "vn100_score")
    if latest is None:
        raise ValueError("Không có dòng VN100 score hợp lệ để build AI payload.")

    period = str(latest["period"])
    latest_csad = latest_period_rows(csad, period)
    latest_csad_row = latest_csad.iloc[-1] if not latest_csad.empty else pd.Series(dtype=object)
    latest_sectors = latest_period_rows(sectors, period)
    latest_tickers = latest_period_rows(tickers, period)

    universe = load_universe_tickers(output_dir, outputs)
    parsed = _parsed_tickers(parse_log)
    if not parsed and not tickers.empty and "ticker" in tickers.columns:
        parsed = set(tickers["ticker"].dropna().astype(str).str.upper())
    scored_latest = set()
    valid_score_latest = set()
    if not latest_tickers.empty and "ticker" in latest_tickers.columns:
        scored_latest = set(latest_tickers["ticker"].dropna().astype(str).str.upper())
        if "ticker_health_score" in latest_tickers.columns:
            valid_rows = latest_tickers.dropna(subset=["ticker_health_score"])
            valid_score_latest = set(valid_rows["ticker"].dropna().astype(str).str.upper())
        else:
            valid_score_latest = scored_latest
    missing_score = sorted(set(universe) - valid_score_latest) if universe else sorted(scored_latest - valid_score_latest)
    failed = _failed_tickers(failed_parse_log, parse_log)

    latest_pca = pd.Series(dtype=object)
    if not pca.empty:
        pca_for_period = latest_period_rows(pca, period)
        latest_pca = pca_for_period.iloc[-1] if not pca_for_period.empty else pca.iloc[-1]

    vn100_5q = vn100.dropna(subset=["vn100_score"]).tail(5).copy()
    component_cols = [
        "period",
        "momentum_score",
        "breadth_score",
        "stability_score",
        "profitability_score",
        "csad_quality_score",
    ]
    component_5q = vn100_5q[[c for c in component_cols if c in vn100_5q.columns]].copy()
    vn100_trend_cols = ["period", "vn100_score", "regime", "broadness_label", "coverage_ratio"]
    vn100_trend = vn100_5q[[c for c in vn100_trend_cols if c in vn100_5q.columns]].copy()

    csad_5q = csad[csad["period"].astype(str).isin(vn100_5q["period"].astype(str))].copy() if not csad.empty else pd.DataFrame()
    csad_cols = [
        "period",
        "breadth_raw",
        "breadth_score",
        "csad_raw",
        "csad_quality_raw_score",
        "csad_quality_ema_score",
        "csad_quality_score",
        "positive_ticker_count",
        "negative_ticker_count",
    ]
    csad_5q = csad_5q[[c for c in csad_cols if c in csad_5q.columns]].tail(5)

    top_sector = pd.DataFrame()
    bottom_sector = pd.DataFrame()
    sector_breadth = pd.DataFrame()
    if not latest_sectors.empty:
        sector_cols = [
            "sector",
            "sector_composite_score",
            "sector_momentum_score",
            "sector_breadth_score",
            "sector_stability_score",
            "sector_profitability_score",
            "sector_csad_quality_score",
            "valid_ticker_count",
            "coverage_ratio",
        ]
        current = latest_sectors[[c for c in sector_cols if c in latest_sectors.columns]].copy()
        current = current.sort_values("sector_composite_score", ascending=False)
        top_sector = current.head(5)
        bottom_sector = current.tail(5).sort_values("sector_composite_score")
        sector_breadth = current[["sector", "sector_breadth_score", "valid_ticker_count", "coverage_ratio"]]

    loadings = "N/A"
    if not latest_pca.empty:
        loading_parts = []
        for i in range(1, 4):
            sector_name = latest_pca.get(f"dominant_sector_{i}", "N/A")
            loading = latest_pca.get(f"dominant_sector_{i}_loading", None)
            loading_parts.append(f"{sector_name} ({fmt_num(loading, signed=True)})")
        loadings = ", ".join(loading_parts)

    payload = {
        "period": period,
        "period_end_date": _period_end_display(latest.get("period_end_date")),
        "parsed_ticker_count": str(len(parsed)),
        "universe_ticker_count": str(len(universe) or len(parsed)),
        "valid_ticker_count": str(int(latest.get("valid_ticker_count", len(latest_tickers)))),
        "coverage_ratio": fmt_num(latest.get("coverage_ratio"), digits=3),
        "failed_parse_tickers": ", ".join(failed) if failed else "None",
        "missing_score_tickers": ", ".join(missing_score) if missing_score else "None",
        "vn100_score": fmt_num(latest.get("vn100_score"), digits=6),
        "regime": str(latest.get("regime", "N/A")),
        "broadness_label": str(latest.get("broadness_label", "N/A")),
        "momentum_score": fmt_num(latest.get("momentum_score"), signed=True),
        "breadth_score": fmt_num(latest.get("breadth_score"), signed=True),
        "stability_score": fmt_num(latest.get("stability_score"), signed=True),
        "profitability_score": fmt_num(latest.get("profitability_score"), signed=True),
        "csad_quality_score": fmt_num(latest.get("csad_quality_score"), signed=True),
        "breadth_raw": fmt_num(latest_csad_row.get("breadth_raw"), digits=3),
        "positive_ticker_count": str(int(latest_csad_row.get("positive_ticker_count", 0))) if not latest_csad_row.empty else "N/A",
        "negative_ticker_count": str(int(latest_csad_row.get("negative_ticker_count", 0))) if not latest_csad_row.empty else "N/A",
        "csad_raw": fmt_num(latest_csad_row.get("csad_raw"), digits=6),
        "csad_quality_raw_score": fmt_num(latest_csad_row.get("csad_quality_raw_score"), signed=True),
        "csad_quality_ema_score": fmt_num(latest_csad_row.get("csad_quality_ema_score"), signed=True),
        "vn100_5q_trend_table": frame_to_markdown(vn100_trend),
        "component_5q_trend_table": frame_to_markdown(component_5q),
        "breadth_csad_5q_trend_table": frame_to_markdown(csad_5q),
        "vn100_score_4q_change": four_quarter_change(vn100, "vn100_score"),
        "momentum_4q_change": four_quarter_change(vn100, "momentum_score"),
        "breadth_4q_change": four_quarter_change(vn100, "breadth_score"),
        "stability_4q_change": four_quarter_change(vn100, "stability_score"),
        "profitability_4q_change": four_quarter_change(vn100, "profitability_score"),
        "csad_quality_4q_change": four_quarter_change(vn100, "csad_quality_score"),
        "top_sector_table": frame_to_markdown(top_sector),
        "bottom_sector_table": frame_to_markdown(bottom_sector),
        "sector_breadth_table": frame_to_markdown(sector_breadth),
        "pca_factor_score": fmt_num(latest_pca.get("pca_factor_score") if not latest_pca.empty else None, signed=True),
        "pc1_explained_variance": fmt_pct(latest_pca.get("pc1_explained_variance") if not latest_pca.empty else None),
        "corr_ew_composite_pc1": fmt_num(latest_pca.get("corr_ew_composite_pc1") if not latest_pca.empty else None),
        "common_factor_label": str(latest_pca.get("common_factor_label", "N/A")) if not latest_pca.empty else "N/A",
        "one_factor_shock_flag": str(latest_pca.get("one_factor_shock_flag", "N/A")) if not latest_pca.empty else "N/A",
        "dominant_sector_loadings": loadings,
    }
    return payload


def fill_prompt_template(template: str, payload: dict[str, str]) -> str:
    prompt = template
    for key, value in payload.items():
        prompt = prompt.replace(f"[{key}]", str(value))
    return prompt
