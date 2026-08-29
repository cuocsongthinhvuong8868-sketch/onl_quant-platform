import json

import pandas as pd

from tools.bank_valuation.quant.engine.data_loader import DataLoader
from tools.bank_valuation.quant.engine.normalize import normalize_data
from tools.bank_valuation.quant.pipeline import run_bank_valuation_pipeline, wide_market_data_to_ohlcv


def test_wide_market_data_to_ohlcv_filters_tickers_and_converts_prices():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    close = pd.DataFrame(
        {
            "ACB": [20.5, 21.0],
            "VCB": [60.0, None],
        },
        index=dates,
    )
    volume = pd.DataFrame(
        {
            "ACB": [1000, 2000],
            "VCB": [3000, 4000],
        },
        index=dates,
    )

    out = wide_market_data_to_ohlcv(close, volumes=volume, tickers=["ACB"])

    assert list(out["ticker"].unique()) == ["ACB"]
    assert list(out["close"]) == [20500.0, 21000.0]
    assert list(out["open"]) == [20500.0, 21000.0]
    assert list(out["high"]) == [20500.0, 21000.0]
    assert list(out["low"]) == [20500.0, 21000.0]
    assert list(out["volume"]) == [1000, 2000]


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_current_schema_files(tmp_path):
    _write_json(
        tmp_path / "ACB_financial_report.json",
        {
            "ticker": "ACB",
            "financialData": {
                "Balance Sheet": {
                    "tableRows": [
                        ["Đơn vị: tỷ VNĐ", "Q1 2026", "Q2 2026"],
                        ["OWNER'S EQUITY\n▲ 4.2%", "95000", "100000"],
                        ["TOTAL ASSETS\n▲ 3.6%", "950000", "1000000"],
                        ["Loans and advances to customers\n▲ 5.2%", "760000", "800000"],
                        ["Deposits from customers\n▲ 4.0%", "780000", "820000"],
                        ["Intangible fixed assets\n▼ 0.8%", "2000", "1900"],
                        ["CAR\n▲ 0.2%", "12.3", "12.5"],
                    ]
                },
                "Income Statement": {
                    "tableRows": [
                        ["Đơn vị: tỷ VNĐ", "Q1 2026", "Q2 2026"],
                        ["Net profit/(loss) after tax\n▲ 8.0%", "4000", "4500"],
                    ]
                },
            },
        },
    )
    _write_json(
        tmp_path / "ACB_financial_statistics.json",
        {
            "schemaVersion": "mozyfin_financial_statistics_v2",
            "ticker": "ACB",
            "financialStatistics": {
                "apiResponses": [
                    {
                        "url": "https://api.mozyfin.com/api/v1/market/exchange/entity/ACB.VN/financial-statistic?entity_id=ACB.VN",
                        "parsedBody": {
                            "data": [
                                {
                                    "year": 2026,
                                    "quarter": 2,
                                    "number_of_shares_market_cap": 5_000_000_000,
                                    "market_cap": 110_000_000_000_000,
                                    "pb": 1.1,
                                    "roe": 0.18,
                                    "roa": 0.018,
                                    "ldr_loan_deposit_ratio": 0.98,
                                    "npl": 0.012,
                                    "loans_loss_reserves_to_npls": -1.2,
                                    "provision_to_outstanding_loans": -0.008,
                                    "car": None,
                                }
                            ]
                        },
                    }
                ]
            },
        },
    )


def test_data_loader_supports_live_trend_labels_and_v2_statistics(tmp_path):
    _write_current_schema_files(tmp_path)
    raw = DataLoader(str(tmp_path)).load_all()
    normalized = normalize_data(raw)
    latest = normalized.loc[normalized["period"] == "Q2 2026"].iloc[0]

    assert latest["equity"] == 100000.0
    assert latest["total_assets"] == 1000000.0
    assert latest["shares_outstanding"] == 5.0
    assert latest["roe"] == 0.18
    assert latest["npl_ratio"] == 0.012
    assert latest["provision_coverage"] == 1.2
    assert latest["credit_cost"] == 0.008
    assert latest["car"] == 0.125


def test_pipeline_values_current_mozyfin_schema_instead_of_returning_all_nan(tmp_path):
    _write_current_schema_files(tmp_path)
    prices = pd.DataFrame({"ACB": [21.0, 22.0]}, index=pd.to_datetime(["2026-08-25", "2026-08-26"]))

    result, _ = run_bank_valuation_pipeline(
        close_prices=prices,
        assumptions={
            "project": {
                "data_folder": str(tmp_path),
                "manual_car_file": str(tmp_path / "missing_manual_car.csv"),
            }
        },
        include_market_confirmation=False,
    )

    latest = result.iloc[0]
    assert latest["reported_equity"] == 100000.0
    assert pd.notna(latest["fair_value_per_share_rim"])
    assert pd.notna(latest["valuation_gap_pct"])
