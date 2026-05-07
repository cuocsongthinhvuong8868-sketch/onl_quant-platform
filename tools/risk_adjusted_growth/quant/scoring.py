import numpy as np
import pandas as pd


def compute_scores(df_base: pd.DataFrame, k_value: float, coe_decimal: float, bvps_change_pct: float, pb_penalty_pct: float) -> pd.DataFrame:
    df = df_base.copy()

    bvps_multiplier = 1.0 + (bvps_change_pct / 100.0)
    pb_penalty_multiplier = 1.0 + (pb_penalty_pct / 100.0)

    df["P/B Kịch Bản"] = (df["P/B Gốc"] / bvps_multiplier) * pb_penalty_multiplier
    df["ROE Retention"] = df["Geomean ROE"] * (1.0 - df["Cash Payout Ratio"])
    df["Risk Penalty"] = k_value * df["Stdev ROE"]
    df["Disciplined Return"] = np.where(
        df["P/B Kịch Bản"] > 0,
        (df["ROE Retention"] / df["P/B Kịch Bản"]) - df["Risk Penalty"],
        0.0,
    )
    df["Economic Alpha"] = df["Disciplined Return"] - coe_decimal

    return df.sort_values(by="Economic Alpha", ascending=False).reset_index(drop=True)
