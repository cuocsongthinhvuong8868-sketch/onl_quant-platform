import numpy as np
import pandas as pd
import pytest

from tools.credit_spread.quant.metrics import (
    calculate_benchmark_spreads,
    calculate_credit_spread,
    normalize_issuance_data,
)


def _issuance_frame():
    return pd.DataFrame(
        {
            "report_date": [
                "2026-01-02", "2026-01-02", "2026-01-02", "2026-01-02",
                "2026-01-09", "2026-01-09", "2026-01-09", "2026-01-16",
            ],
            "sector": [
                "bank", "bank", "real_estate", "real_estate",
                "bank", "real_estate", "non_bank_corp", "bank",
            ],
            "coupon_rate_pct": [6.0, 8.0, 10.0, 12.0, 7.0, 10.0, 15.0, 8.0],
            "issue_value_bn_vnd": [100.0, 300.0, 100.0, 100.0, 200.0, 400.0, 50.0, 100.0],
            "maturity_bucket": ["<=3Y"] * 8,
        }
    )


def test_equal_weight_spread_and_return_follow_supplied_formula():
    result = calculate_credit_spread(_issuance_frame(), weighting="equal")

    first = result.loc[pd.Timestamp("2026-01-02")]
    second = result.loc[pd.Timestamp("2026-01-09")]
    assert first["bank_yield_pct"] == pytest.approx(7.0)
    assert first["real_estate_yield_pct"] == pytest.approx(11.0)
    assert first["signed_spread_pct"] == pytest.approx(-4.0)
    assert first["risk_premium_bps"] == pytest.approx(400.0)
    assert first["risk_premium_percentile"] == pytest.approx(100.0)
    assert second["signed_spread_pct"] == pytest.approx(-3.0)
    assert second["spread_return_pct"] == pytest.approx(25.0)
    assert second["risk_premium_percentile"] == pytest.approx(50.0)
    assert second["direction"] == "NARROWING"


def test_issue_value_weighting_and_unmatched_dates():
    result = calculate_credit_spread(_issuance_frame(), weighting="issue_value")

    assert list(result.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-09")]
    assert result.iloc[0]["bank_yield_pct"] == pytest.approx(7.5)
    assert result.iloc[0]["real_estate_yield_pct"] == pytest.approx(11.0)


def test_maturity_filter_can_return_empty_matched_frame():
    result = calculate_credit_spread(_issuance_frame(), maturity_buckets=[">5Y"])
    assert result.empty
    assert list(result.columns)[0] == "bank_yield_pct"


def test_zero_lag_spread_does_not_produce_infinite_return():
    frame = _issuance_frame().iloc[:0].copy()
    frame.loc[0] = ["2026-01-02", "bank", 8.0, 100.0, "<=3Y"]
    frame.loc[1] = ["2026-01-02", "real_estate", 8.0, 100.0, "<=3Y"]
    frame.loc[2] = ["2026-01-09", "bank", 8.0, 100.0, "<=3Y"]
    frame.loc[3] = ["2026-01-09", "real_estate", 9.0, 100.0, "<=3Y"]

    result = calculate_credit_spread(frame)
    assert np.isnan(result.iloc[1]["spread_return_pct"])
    assert result.iloc[1]["direction"] == "WIDENING"


def test_schema_validation_is_explicit():
    with pytest.raises(ValueError, match="coupon_rate_pct"):
        normalize_issuance_data(pd.DataFrame({"report_date": ["2026-01-01"]}))


def test_government_benchmark_uses_prior_observation_and_bucket_proxy():
    corporate = pd.DataFrame(
        {
            "report_date": ["2026-01-10", "2026-01-10"],
            "sector": ["bank", "real_estate"],
            "maturity_bucket": ["<=3Y", "<=3Y"],
            "yield_avg_pct": [7.0, 10.0],
        }
    )
    government = pd.DataFrame(
        {
            "date": ["2026-01-09", "2026-01-11"],
            "tenor": ["3Y", "3Y"],
            "yield_pct": [3.0, 2.0],
        }
    )

    result = calculate_benchmark_spreads(corporate, government)
    assert set(result["government_tenor"]) == {"3Y"}
    assert set(result["government_date"]) == {pd.Timestamp("2026-01-09")}
    assert result.loc[result["sector"].eq("bank"), "government_spread_bps"].iloc[0] == pytest.approx(400.0)
