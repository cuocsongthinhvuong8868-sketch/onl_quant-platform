import numpy as np
import pandas as pd

from tools.global_financial_conditions.quant.metrics import (
    RAW_COLUMNS,
    process_gfcm_logic,
)


def _sample_gfcm_raw(rows: int = 620) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=rows)
    base = np.arange(rows, dtype=float)
    data = {}
    for offset, column in enumerate(RAW_COLUMNS):
        data[column] = 100.0 + offset * 10.0 + 0.01 * base + np.sin(base / (7 + offset))
    return pd.DataFrame(data, index=index)


def test_indicator_percentiles_use_3y_window_with_1y_warmup():
    df_raw = _sample_gfcm_raw()

    df_processed, meta = process_gfcm_logic(df_raw)

    assert meta["zscore_window"] == 252
    assert meta["series_percentile_window"] == 756
    assert meta["series_percentile_min_periods"] == 252
    assert meta["pc1_percentile_window"] == 252

    assert pd.isna(df_processed["VIX_pct"].iloc[250])
    assert pd.notna(df_processed["VIX_pct"].iloc[251])
    assert pd.notna(df_processed["HY_pct"].iloc[-1])
    assert pd.notna(df_processed["PC1_pct"].iloc[-1])


def test_strict_3y_percentile_would_blank_short_credit_history():
    df_raw = _sample_gfcm_raw()

    df_processed, _ = process_gfcm_logic(df_raw, pct_min_periods=756)

    assert df_processed["VIX_pct"].isna().all()
    assert df_processed["HY_pct"].isna().all()
