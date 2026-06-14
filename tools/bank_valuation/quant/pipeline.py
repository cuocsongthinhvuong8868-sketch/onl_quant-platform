from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Iterable

import pandas as pd

from config import DATA_LAKE
from tools.bank_valuation.quant.engine.capital_model import calculate_capital_dilution_risk
from tools.bank_valuation.quant.engine.collateral_risk import calculate_collateral_risk_score
from tools.bank_valuation.quant.engine.credit_cycle import calculate_credit_cycle_score
from tools.bank_valuation.quant.engine.data_loader import DataLoader
from tools.bank_valuation.quant.engine.data_quality import calculate_data_quality_flag
from tools.bank_valuation.quant.engine.funding_quality import calculate_funding_quality_score
from tools.bank_valuation.quant.engine.manual_overrides import apply_manual_car_overrides
from tools.bank_valuation.quant.engine.market_confirmation import (
    calculate_market_betas,
    calculate_market_confirmation,
)
from tools.bank_valuation.quant.engine.metrics import calculate_core_metrics
from tools.bank_valuation.quant.engine.normalize import normalize_data
from tools.bank_valuation.quant.engine.relative_value import (
    RELATIVE_VALUE_COLUMNS,
    calculate_relative_value,
)
from tools.bank_valuation.quant.engine.schema import ValuationOutput
from tools.bank_valuation.quant.engine.scoring import calculate_final_scores_and_classification
from tools.bank_valuation.quant.engine.stress_test import run_scenario_valuation


logger = logging.getLogger(__name__)

BANK_VALUATION_DATA_DIR = DATA_LAKE / "bank_valuation"
BCTC_JSON_DIR = BANK_VALUATION_DATA_DIR / "bctc_json"
MANUAL_CAR_FILE = BANK_VALUATION_DATA_DIR / "manual_car.csv"
PRICE_THOUSANDS_TO_VND = 1000.0

DEFAULT_ASSUMPTIONS = {
    "project": {
        "name": "vn-bank-valuation-stack",
        "base_currency": "VND",
        "data_folder": str(BCTC_JSON_DIR),
        "manual_car_file": str(MANUAL_CAR_FILE),
    },
    "valuation": {
        "forecast_years": 5,
        "terminal_growth": 0.045,
        "default_beta": 1.10,
        "risk_free_rate": 0.045,
        "market_erp": 0.081,
        "default_payout_ratio": 0.30,
        "max_justified_pb": 5.0,
        "min_justified_pb": 0.2,
    },
    "credit": {
        "target_provision_coverage_base": 1.00,
        "target_provision_coverage_bear": 1.20,
        "target_provision_coverage_stress": 1.50,
        "group2_to_npl_migration_base": 0.15,
        "group2_to_npl_migration_bear": 0.25,
        "group2_to_npl_migration_stress": 0.40,
        "lgd_base": 0.35,
        "lgd_bear": 0.45,
        "lgd_stress": 0.55,
        "credit_cost_floor_base": 0.008,
        "credit_cost_floor_bear": 0.012,
        "credit_cost_floor_stress": 0.018,
    },
    "risk_premium": {
        "credit_cycle_risk_premium_max": 0.020,
        "capital_risk_premium_max": 0.015,
        "collateral_risk_premium_max": 0.020,
        "governance_risk_premium_default": 0.005,
    },
    "pb_adjustments": {
        "funding_pb_sensitivity": 0.003,
        "credit_pb_discount_sensitivity": 0.004,
        "collateral_pb_discount_sensitivity": 0.003,
        "capital_pb_discount_sensitivity": 0.003,
    },
    "sustainable_roe_weights": {
        "latest_normalized_roe": 0.40,
        "three_year_median_roe": 0.40,
        "stress_adjusted_roe": 0.20,
    },
    "scenarios": {
        "bull": {
            "nim_shock": 0.002,
            "credit_cost_shock": -0.002,
            "loan_growth_multiplier": 1.10,
            "fee_income_multiplier": 1.05,
            "pb_risk_discount": -0.05,
        },
        "base": {
            "nim_shock": 0.000,
            "credit_cost_shock": 0.000,
            "loan_growth_multiplier": 1.00,
            "fee_income_multiplier": 1.00,
            "pb_risk_discount": 0.00,
        },
        "bear": {
            "nim_shock": -0.003,
            "credit_cost_shock": 0.005,
            "loan_growth_multiplier": 0.75,
            "fee_income_multiplier": 0.90,
            "pb_risk_discount": 0.15,
        },
        "stress": {
            "nim_shock": -0.007,
            "credit_cost_shock": 0.012,
            "loan_growth_multiplier": 0.50,
            "fee_income_multiplier": 0.80,
            "collateral_lgd_shock": 0.15,
            "pb_risk_discount": 0.30,
        },
    },
}


def bank_valuation_source_signature(
    data_dir: str | Path = BCTC_JSON_DIR,
    manual_car_file: str | Path = MANUAL_CAR_FILE,
) -> str:
    files = sorted(Path(data_dir).glob("*.json"))
    manual_path = Path(manual_car_file)
    if manual_path.exists():
        files.append(manual_path)
    if not files:
        return "NO_BANK_VALUATION_FEED"

    digest = hashlib.sha1()
    latest_timestamp = ""
    for file_path in files:
        raw = file_path.read_bytes()
        digest.update(file_path.name.encode("utf-8"))
        digest.update(raw)
        if file_path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        latest_timestamp = max(latest_timestamp, str(payload.get("timestamp", "")))

    if latest_timestamp:
        parsed = pd.to_datetime(latest_timestamp, errors="coerce")
        date_label = latest_timestamp[:10] if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")
    else:
        latest_mtime = max(file_path.stat().st_mtime for file_path in files)
        date_label = pd.to_datetime(latest_mtime, unit="s").strftime("%Y-%m-%d")
    return f"{date_label}:{digest.hexdigest()[:12]}"


def wide_market_data_to_ohlcv(
    close_prices: pd.DataFrame,
    volumes: pd.DataFrame | None = None,
    tickers: Iterable[str] | None = None,
) -> pd.DataFrame:
    if close_prices is None or close_prices.empty:
        return pd.DataFrame(columns=["time", "ticker", "open", "high", "low", "close", "volume"])

    if tickers is None:
        cols = list(close_prices.columns)
    else:
        wanted = {str(t).upper().strip() for t in tickers if str(t).strip()}
        cols = [col for col in close_prices.columns if str(col).upper() in wanted]
    if not cols:
        return pd.DataFrame(columns=["time", "ticker", "open", "high", "low", "close", "volume"])

    close = close_prices[cols].copy()
    close.index = pd.to_datetime(close.index, errors="coerce")
    close = close.sort_index()
    long_close = (
        close.stack(future_stack=True)
        .dropna()
        .rename("close")
        .reset_index()
        .rename(columns={"level_0": "time", "level_1": "ticker"})
    )
    if long_close.empty:
        return pd.DataFrame(columns=["time", "ticker", "open", "high", "low", "close", "volume"])

    long_close["ticker"] = long_close["ticker"].astype(str).str.upper()
    long_close["close"] = pd.to_numeric(long_close["close"], errors="coerce") * PRICE_THOUSANDS_TO_VND
    for col in ["open", "high", "low"]:
        long_close[col] = long_close["close"]

    if volumes is not None and not volumes.empty:
        vol_cols = [col for col in cols if col in volumes.columns]
        if vol_cols:
            volume = volumes[vol_cols].copy()
            volume.index = pd.to_datetime(volume.index, errors="coerce")
            long_volume = (
                volume.stack(future_stack=True)
                .dropna()
                .rename("volume")
                .reset_index()
                .rename(columns={"level_0": "time", "level_1": "ticker"})
            )
            long_volume["ticker"] = long_volume["ticker"].astype(str).str.upper()
            long_close = long_close.merge(long_volume, on=["time", "ticker"], how="left")
        else:
            long_close["volume"] = pd.NA
    else:
        long_close["volume"] = pd.NA

    return long_close[["time", "ticker", "open", "high", "low", "close", "volume"]].dropna(
        subset=["time", "ticker", "close"]
    )


def _missing(value) -> bool:
    return pd.isna(value)


def _add_output_warnings(
    out: ValuationOutput,
    row: pd.Series,
    metrics: dict,
    base: dict,
    market_price: float,
) -> None:
    checks = [
        (
            _missing(row.get("shares_outstanding", float("nan"))) or row.get("shares_outstanding", 0) <= 0,
            "shares_outstanding missing or zero; per-share valuation confidence reduced",
        ),
        (_missing(market_price) or market_price <= 0, "market price missing; valuation gap unavailable"),
        (
            _missing(row.get("npl_balance", float("nan"))) and _missing(metrics.get("npl_ratio", float("nan"))),
            "NPL data missing; credit-risk confidence reduced",
        ),
        (_missing(metrics.get("group2_ratio", float("nan"))), "group 2 loans missing; hidden NPL adjustment skipped"),
        (
            _missing(metrics.get("provision_coverage", float("nan"))),
            "provision coverage missing; under-provisioning confidence reduced",
        ),
        (_missing(metrics.get("casa_ratio", float("nan"))), "CASA data missing; funding quality confidence reduced"),
        (_missing(metrics.get("ldr", float("nan"))), "LDR missing; funding quality confidence reduced"),
        (
            _missing(metrics.get("car", float("nan"))),
            "CAR missing or invalid; capital dilution risk uses fallback assumptions",
        ),
        (_missing(row.get("beta", float("nan"))), "beta missing; default beta used for cost of equity"),
        (_missing(base.get("fair_value_rim", float("nan"))), "RIM fair value unavailable"),
    ]
    for condition, message in checks:
        if condition:
            out.add_warning(message)

    for message in base.get("warnings", []):
        out.add_warning(message)


def _parse_period_rank(period) -> int:
    try:
        quarter, year = str(period).split()
        return int(year) * 10 + int(quarter[1])
    except (IndexError, TypeError, ValueError):
        logger.warning("Could not parse reporting period %r; sorting it first.", period)
        return 0


def _apply_relative_value(results: list[ValuationOutput]) -> None:
    if not results:
        return

    relative_df = calculate_relative_value(pd.DataFrame([r.to_dict() for r in results]))
    rel_rows = {
        (row["ticker"], row["period"]): row
        for _, row in relative_df.iterrows()
    }
    for result in results:
        row = rel_rows.get((result.ticker, result.period))
        if row is None:
            continue
        for col in RELATIVE_VALUE_COLUMNS:
            setattr(result, col, row.get(col, getattr(result, col)))


def _apply_data_quality_flags(results: list[ValuationOutput]) -> None:
    for result in results:
        result.data_quality_flag = calculate_data_quality_flag(result.to_dict())


def _latest_price_map(close_prices: pd.DataFrame | None) -> tuple[dict[str, float], str]:
    if close_prices is None or close_prices.empty:
        return {}, "n/a"
    prices = close_prices.sort_index().ffill()
    latest_date = pd.to_datetime(prices.index.max()).strftime("%Y-%m-%d")
    row = prices.iloc[-1]
    out = {}
    for ticker, value in row.items():
        price = pd.to_numeric(value, errors="coerce")
        if pd.notna(price) and price > 0:
            out[str(ticker).upper()] = float(price) * PRICE_THOUSANDS_TO_VND
    return out, latest_date


def run_bank_valuation_pipeline(
    close_prices: pd.DataFrame | None = None,
    volumes: pd.DataFrame | None = None,
    assumptions: dict | None = None,
    ticker: str | None = None,
    include_market_confirmation: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = DEFAULT_ASSUMPTIONS.copy()
    if assumptions:
        config.update(assumptions)

    data_folder = config.get("project", {}).get("data_folder", str(BCTC_JSON_DIR))
    loader = DataLoader(str(data_folder))
    raw = loader.load_all()
    if raw.empty:
        raise ValueError(f"No bank valuation input data found in {data_folder}.")

    if ticker:
        raw = raw[raw["ticker"].astype(str).str.upper() == ticker.upper()]
    if raw.empty:
        raise ValueError(f"No bank valuation rows found for ticker={ticker}.")

    data = normalize_data(raw)
    manual_car_file = config.get("project", {}).get("manual_car_file", str(MANUAL_CAR_FILE))
    data = apply_manual_car_overrides(data, manual_car_file)

    latest_prices, price_date = _latest_price_map(close_prices)
    if latest_prices:
        data["price"] = data["ticker"].astype(str).str.upper().map(latest_prices)

    if "equity" in data.columns:
        data = data.dropna(subset=["equity"])
    if data.empty:
        raise ValueError("Bank valuation data is empty after equity filtering.")

    data["period_rank"] = data["period"].apply(_parse_period_rank)
    data = data.sort_values(by=["ticker", "period_rank"])
    if "car" in data.columns:
        data["car"] = pd.to_numeric(data["car"], errors="coerce")
        data.loc[data["car"] <= 0, "car"] = float("nan")
        data["car"] = data.groupby("ticker")["car"].ffill()
        for col in ["car_source", "car_disclosure_date"]:
            if col in data.columns:
                data[col] = data.groupby("ticker")[col].ffill()

    tickers = sorted(data["ticker"].dropna().astype(str).str.upper().unique())
    ohlcv_df = wide_market_data_to_ohlcv(close_prices, volumes=volumes, tickers=tickers)
    beta_df = calculate_market_betas(ohlcv_df)
    if not beta_df.empty:
        beta_df = beta_df[["ticker", "beta", "beta_observations", "beta_benchmark"]]
        data = data.merge(beta_df, on="ticker", how="left", suffixes=("", "_estimated"))
    if "beta" not in data.columns:
        data["beta"] = float("nan")

    results: list[ValuationOutput] = []
    for _, row in data.iterrows():
        try:
            bank_ticker = row["ticker"]
            period = row["period"]
            metrics = calculate_core_metrics(row)
            cc = calculate_credit_cycle_score(row, metrics)
            col = calculate_collateral_risk_score(row, metrics)
            fun = calculate_funding_quality_score(row, metrics)
            cap = calculate_capital_dilution_risk(row, metrics, config)
            risk_scores = {**cc, **col, **fun, **cap}
            risk_scores["beta"] = row.get("beta", float("nan"))

            history_df = data[(data["ticker"] == bank_ticker) & (data["period_rank"] <= row["period_rank"])]
            scenarios = run_scenario_valuation(row, history_df, metrics, risk_scores, config)
            base = scenarios["base"]
            stress = scenarios["stress"]

            market_price = row.get("price", float("nan"))
            market_pb = metrics.get("market_pb", float("nan"))
            if (
                pd.isna(market_pb)
                and not pd.isna(market_price)
                and not pd.isna(base.get("book_value_per_share", float("nan")))
                and base["book_value_per_share"] > 0
            ):
                market_pb = market_price / base["book_value_per_share"]

            gap = float("nan")
            if not pd.isna(market_price) and market_price > 0 and not pd.isna(base["fair_value_rim"]):
                gap = (base["fair_value_rim"] / market_price) - 1

            stress_downside = float("nan")
            if not pd.isna(market_price) and market_price > 0 and not pd.isna(stress["fair_value_rim"]):
                stress_downside = (stress["fair_value_rim"] / market_price) - 1

            final_scores = calculate_final_scores_and_classification(risk_scores, gap, stress_downside)
            out = ValuationOutput(
                ticker=bank_ticker,
                period=period,
                price=market_price,
                beta=row.get("beta", float("nan")),
                shares_outstanding=row.get("shares_outstanding", float("nan")),
                reported_equity=row.get("equity", float("nan")),
                adjusted_equity=base.get("adjusted_equity", float("nan")),
                book_value_per_share=base.get("book_value_per_share", float("nan")),
                adjusted_book_value_per_share=base["adjusted_bvps"],
                tangible_book_value_per_share=base.get("tangible_book_value_per_share", float("nan")),
                reported_roe=metrics.get("reported_roe", float("nan")),
                normalized_roe=base.get("normalized_roe", float("nan")),
                sustainable_roe=base["sustainable_roe"],
                stress_adjusted_roe=stress.get("stress_adjusted_roe", float("nan")),
                cost_of_equity=base["cost_of_equity"],
                justified_pb=base["justified_pb"],
                market_pb=market_pb,
                fair_value_per_share_rim=base["fair_value_rim"],
                fair_value_per_share_pb=base["fair_value_pb"],
                stress_value_per_share=stress["fair_value_rim"],
                valuation_gap_pct=gap,
                npl_ratio=metrics.get("npl_ratio", float("nan")),
                group2_ratio=metrics.get("group2_ratio", float("nan")),
                credit_cost=metrics.get("credit_cost", float("nan")),
                provision_coverage=metrics.get("provision_coverage", float("nan")),
                casa_ratio=metrics.get("casa_ratio", float("nan")),
                ldr=metrics.get("ldr", float("nan")),
                car=metrics.get("car", float("nan")),
                car_source=row.get("car_source", ""),
                car_disclosure_date=row.get("car_disclosure_date", ""),
                cet1_proxy=metrics.get("cet1_proxy", float("nan")),
                capital_dilution_risk_score=risk_scores["capital_dilution_risk_score"],
                credit_cycle_score=risk_scores["credit_cycle_score"],
                funding_quality_score=risk_scores["funding_quality_score"],
                collateral_risk_score=risk_scores["collateral_risk_score"],
                overall_risk_score=final_scores["overall_risk_score"],
                classification=final_scores["classification"],
            )
            _add_output_warnings(out, row, metrics, base, market_price)
            results.append(out)
        except Exception:
            logger.exception("Error processing ticker=%s period=%s", row.get("ticker"), row.get("period"))

    _apply_relative_value(results)
    _apply_data_quality_flags(results)
    output = pd.DataFrame([r.to_dict() for r in results])
    if output.empty:
        return output, ohlcv_df

    output["_period_rank"] = output["period"].apply(_parse_period_rank)
    latest = (
        output.sort_values(["ticker", "_period_rank"])
        .drop_duplicates("ticker", keep="last")
        .drop(columns=["_period_rank"])
        .reset_index(drop=True)
    )
    if include_market_confirmation:
        latest = calculate_market_confirmation(latest, ohlcv_df)

    latest.attrs["source_signature"] = bank_valuation_source_signature()
    latest.attrs["price_date"] = price_date
    latest.attrs["bctc_json_dir"] = str(BCTC_JSON_DIR)
    return latest, ohlcv_df
