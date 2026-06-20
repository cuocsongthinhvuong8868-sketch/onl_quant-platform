from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .aggregation import (
    add_breadth_diffusion_to_companies,
    compute_sector_diffusion,
    compute_sector_scores,
    compute_vn100_scores,
)
from .config import OUTPUT_DIR
from .diagnostics import add_company_flags, build_alerts, build_diagnostic_json
from .loader import LoadedData, load_all
from .matrices import (
    compute_company_rolling_consistency,
    compute_core_consistency_matrix,
    compute_matrix_consistency_score,
    compute_pca_factor,
    compute_transmission_matrix,
)
from .normalizer import add_ttm_and_growth
from .scoring import add_core_scores, add_sector_relative_fields, composite_health_score


@dataclass
class PipelineResult:
    loaded: LoadedData
    metrics: pd.DataFrame
    company_scores: pd.DataFrame
    sector_scores: pd.DataFrame
    vn100_scores: pd.DataFrame
    core_consistency_matrix: pd.DataFrame
    company_rolling_consistency: pd.DataFrame
    transmission_matrix: pd.DataFrame
    pca_factor: pd.DataFrame
    pca_loadings: pd.DataFrame
    alerts: pd.DataFrame


def _drop_existing_sector_columns(df: pd.DataFrame) -> pd.DataFrame:
    drop_cols = [
        "sector_health_score",
        "sector_growth_score",
        "sector_cash_conversion_score",
        "sector_working_capital_stress",
        "sector_leverage_stress",
        "sector_diffusion_label",
        "sector_diffusion_score",
        "breadth_diffusion_score",
    ]
    return df.drop(columns=[col for col in drop_cols if col in df], errors="ignore")


def run_pipeline() -> PipelineResult:
    loaded = load_all()
    metrics = add_ttm_and_growth(loaded.canonical)
    scored = add_core_scores(metrics)

    core_matrix = compute_core_consistency_matrix(scored)
    rolling_detail, rolling_summary = compute_company_rolling_consistency(scored)
    transmission_detail, transmission_summary = compute_transmission_matrix(scored)
    matrix_summary = compute_matrix_consistency_score(rolling_summary, transmission_summary)
    scored = scored.merge(
        matrix_summary[
            [
                "ticker",
                "period",
                "rolling_consistency_score",
                "transmission_score",
                "matrix_consistency_score",
            ]
        ],
        on=["ticker", "period"],
        how="left",
    )

    scored["matrix_consistency_score"] = scored["matrix_consistency_score"].fillna(50)
    scored["corporate_health_score"] = composite_health_score(
        scored, matrix_col="matrix_consistency_score", breadth_col=None
    )

    for _ in range(2):
        sector_scores = compute_sector_scores(scored)
        sector_diffusion = compute_sector_diffusion(sector_scores)
        scored = _drop_existing_sector_columns(scored)
        scored = add_breadth_diffusion_to_companies(scored, sector_scores, sector_diffusion)
        scored["corporate_health_score"] = composite_health_score(
            scored,
            matrix_col="matrix_consistency_score",
            breadth_col="breadth_diffusion_score",
        )

    sector_scores = compute_sector_scores(scored)
    sector_diffusion = compute_sector_diffusion(sector_scores)
    scored = _drop_existing_sector_columns(scored)
    scored = add_breadth_diffusion_to_companies(scored, sector_scores, sector_diffusion)
    scored["corporate_health_score"] = composite_health_score(
        scored,
        matrix_col="matrix_consistency_score",
        breadth_col="breadth_diffusion_score",
    )
    scored = add_company_flags(scored)
    scored = add_sector_relative_fields(scored)

    sector_scores = compute_sector_scores(scored)
    sector_diffusion = compute_sector_diffusion(sector_scores)
    vn100_scores = compute_vn100_scores(scored, sector_scores, sector_diffusion)
    pca_factor, pca_loadings = compute_pca_factor(scored)
    alerts = build_alerts(scored)

    return PipelineResult(
        loaded=loaded,
        metrics=metrics,
        company_scores=scored.sort_values(["period_order", "ticker"]).reset_index(drop=True),
        sector_scores=sector_scores,
        vn100_scores=vn100_scores,
        core_consistency_matrix=core_matrix,
        company_rolling_consistency=rolling_detail,
        transmission_matrix=transmission_detail,
        pca_factor=pca_factor,
        pca_loadings=pca_loadings,
        alerts=alerts,
    )


def _csv_safe(df: pd.DataFrame) -> pd.DataFrame:
    safe = df.copy()
    for col in safe.columns:
        if safe[col].map(lambda x: isinstance(x, (list, dict))).any():
            safe[col] = safe[col].map(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
    return safe


def _write_frame(df: pd.DataFrame, stem: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_dir / f"{stem}.parquet", index=False)
    _csv_safe(df).to_csv(output_dir / f"{stem}.csv", index=False)


def write_outputs(result: PipelineResult, output_dir: Path = OUTPUT_DIR) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_frame(result.loaded.metadata, "ticker_metadata", output_dir)
    result.loaded.statement_long.to_parquet(output_dir / "financial_items_long.parquet", index=False)
    _write_frame(result.metrics, "canonical_financials", output_dir)
    _write_frame(result.company_scores, "company_scores", output_dir)
    _write_frame(result.sector_scores, "sector_scores", output_dir)
    _write_frame(result.vn100_scores, "vn100_scores", output_dir)
    _write_frame(result.core_consistency_matrix, "core_consistency_matrix", output_dir)
    _write_frame(result.company_rolling_consistency, "company_rolling_consistency", output_dir)
    _write_frame(result.transmission_matrix, "transmission_matrix", output_dir)
    _write_frame(result.pca_factor, "pca_factor", output_dir)
    _write_frame(result.pca_loadings, "pca_loadings", output_dir)
    _write_frame(result.alerts, "alerts", output_dir)

    diagnostics = build_diagnostic_json(result.company_scores)
    (output_dir / "diagnostic_flags.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )

    latest_qoq_order = int(result.company_scores["period_order"].max())
    latest_qoq_period = result.company_scores.loc[
        result.company_scores["period_order"] == latest_qoq_order, "period"
    ].iloc[0]
    yoy_candidates = result.company_scores[
        (result.company_scores["year"] <= 2025) & (result.company_scores["quarter"] == 4)
    ]
    if yoy_candidates.empty:
        yoy_candidates = result.company_scores[result.company_scores["year"] <= 2025]
    latest_yoy_order = int(yoy_candidates["period_order"].max())
    latest_yoy_period = yoy_candidates.loc[
        yoy_candidates["period_order"] == latest_yoy_order, "period"
    ].iloc[0]

    snapshots = {
        "company_scores_latest_qoq": result.company_scores[result.company_scores["period_order"] == latest_qoq_order],
        "sector_scores_latest_qoq": result.sector_scores[result.sector_scores["period_order"] == latest_qoq_order],
        "vn100_scores_latest_qoq": result.vn100_scores[result.vn100_scores["period_order"] == latest_qoq_order],
        "company_scores_latest_yoy": result.company_scores[result.company_scores["period_order"] == latest_yoy_order],
        "sector_scores_latest_yoy": result.sector_scores[result.sector_scores["period_order"] == latest_yoy_order],
        "vn100_scores_latest_yoy": result.vn100_scores[result.vn100_scores["period_order"] == latest_yoy_order],
    }
    for stem, df in snapshots.items():
        _write_frame(df, stem, output_dir)

    summary = {
        "tickers": int(result.loaded.metadata["ticker"].nunique()),
        "periods": int(result.company_scores["period"].nunique()),
        "latest_qoq_period": latest_qoq_period,
        "latest_yoy_period": latest_yoy_period,
        "output_dir": str(output_dir),
        "files": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def run_and_write(output_dir: Path = OUTPUT_DIR) -> tuple[PipelineResult, dict]:
    result = run_pipeline()
    summary = write_outputs(result, output_dir)
    return result, summary
