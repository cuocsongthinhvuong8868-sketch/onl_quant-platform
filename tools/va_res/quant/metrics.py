import polars as pl
import numpy as np
from numba import njit
from scipy.stats import norm
from dataclasses import dataclass
from typing import Tuple, Literal

METHOD_VERSION = "vares_v2.0.0"
DEFAULT_MAX_ABS_RETURN = 0.50
STRESS_ALERT_PCT = 40.0
COMPLACENCY_ALERT_PCT = 80.0

@dataclass
class RiskConfig:
    window_years: int = 3
    trading_days: int = 252
    min_periods: int = 252
    confidence: float = 0.95
    ema_smooth_span: int = 20
    trend_ma_window: int = 126
    pr_window: int = 252
    dynamic_multiplier_base: float = 0.8
    max_abs_return: float = DEFAULT_MAX_ABS_RETURN

    @property
    def window_size(self) -> int:
        return self.window_years * self.trading_days

    @property
    def z_score(self) -> float:
        return norm.ppf(1 - self.confidence)

@njit(fastmath=True)
def numba_historical_risk(
    returns: np.ndarray, 
    window: int, 
    min_periods: int, 
    confidence: float
) -> Tuple[np.ndarray, np.ndarray]:
    n = len(returns)
    var_out = np.full(n, np.nan)
    es_out = np.full(n, np.nan)
    
    percentile_q = (1.0 - confidence) * 100.0

    for i in range(n):
        if i < min_periods:
            continue
            
        start_idx = max(0, i - window)
        window_data = returns[start_idx:i]
        
        valid_data = window_data[~np.isnan(window_data)]
        if len(valid_data) < min_periods:
            continue
            
        var_val = np.percentile(valid_data, percentile_q)
        var_out[i] = var_val
        
        tail = valid_data[valid_data <= var_val]
        if len(tail) > 0:
            es_out[i] = np.mean(tail)
        else:
            es_out[i] = var_val
            
    return var_out, es_out

class SystemicRiskEngine:
    def __init__(self, config: RiskConfig = RiskConfig()):
        self.config = config

    def _cornish_fisher_z_enhanced(self, z_score: float, skew: pl.Expr, kurt: pl.Expr) -> Tuple[pl.Expr, pl.Expr]:
        z_cf = (
            z_score
            + (z_score**2 - 1) * skew / 6
            + (z_score**3 - 3 * z_score) * kurt / 24
            - (2 * z_score**3 - 5 * z_score) * (skew**2) / 36
        )
        
        invalid = z_cf.is_null() | (z_cf > 0) | (z_cf.abs() > 5)
        z_final = pl.when(invalid).then(z_score).otherwise(z_cf)
        is_fallback = invalid.cast(pl.Int8)
        
        return z_final, is_fallback

    def calculate_risk_metrics(
        self, 
        df_price: pl.DataFrame, 
        method: Literal['historical', 'cornish_fisher'] = 'historical'
    ) -> pl.DataFrame:
        date_col = df_price.columns[0]
        tickers = df_price.columns[1:]
        
        df_long = (
            df_price
            .unpivot(index=date_col, variable_name="ticker", value_name="price")
            .with_columns(pl.col("price").cast(pl.Float64))
            .sort(["ticker", date_col])
        )
        
        w = self.config.window_size
        min_p = self.config.min_periods
        
        df_calc = df_long.with_columns([
            (pl.col("price") / pl.col("price").shift(1).over("ticker") - 1).alias("return_raw")
        ]).with_columns([
            pl.when(
                pl.col("return_raw").is_finite()
                & (pl.col("return_raw").abs() <= self.config.max_abs_return)
            )
            .then(pl.col("return_raw"))
            .otherwise(None)
            .alias("return")
        ]).with_columns([
            pl.col("return").rolling_mean(window_size=w, min_samples=min_p).over("ticker").alias("mean_raw"),
            pl.col("return").rolling_std(window_size=w, min_samples=min_p).over("ticker").alias("std_raw"),
            pl.col("return").rolling_skew(window_size=w).over("ticker").alias("skew_raw"),
        ]).with_columns([
            (((pl.col("return") - pl.col("mean_raw"))**4).rolling_mean(window_size=w, min_samples=min_p).over("ticker")
             / (pl.col("std_raw")**4) - 3).alias("kurt_raw")
        ]).with_columns([
            pl.col("mean_raw").shift(1).over("ticker").alias("mean"),
            pl.col("std_raw").shift(1).over("ticker").alias("std"),
            pl.col("skew_raw").shift(1).over("ticker").alias("skew"),
            pl.col("kurt_raw").shift(1).over("ticker").alias("kurt"),
        ])

        if method == 'cornish_fisher':
            z_cf, is_fallback = self._cornish_fisher_z_enhanced(self.config.z_score, pl.col("skew"), pl.col("kurt"))
            
            phi_cf = (1 / np.sqrt(2 * np.pi)) * (-0.5 * z_cf**2).exp()
            es_cf = pl.col("mean") - (phi_cf / (1 - self.config.confidence)) * pl.col("std")
            
            phi_z = norm.pdf(self.config.z_score)
            gaussian_es = pl.col("mean") - (phi_z / (1 - self.config.confidence)) * pl.col("std")
            
            df_res = df_calc.with_columns([
                (pl.col("mean") + z_cf * pl.col("std")).alias("VaR"),
                pl.when(is_fallback == 1).then(gaussian_es).otherwise(es_cf).alias("ES")
            ])
            
        else:
            df_ret_wide = df_calc.pivot(index=date_col, on="ticker", values="return").sort(date_col)
            var_dict, es_dict = {date_col: df_ret_wide[date_col]}, {date_col: df_ret_wide[date_col]}
            
            for t in tickers:
                ret_array = df_ret_wide[t].to_numpy()
                var_arr, es_arr = numba_historical_risk(
                    ret_array, w, min_p, self.config.confidence
                )
                var_dict[t] = var_arr
                es_dict[t] = es_arr
                
            df_var_long = pl.DataFrame(var_dict).unpivot(index=date_col, variable_name="ticker", value_name="VaR")
            df_es_long = pl.DataFrame(es_dict).unpivot(index=date_col, variable_name="ticker", value_name="ES")
            
            df_res = df_calc.join(df_var_long, on=[date_col, "ticker"]).join(df_es_long, on=[date_col, "ticker"])

        df_res = df_res.with_columns(
            (pl.col("VaR") - pl.col("ES")).alias("Spread_Raw")
        )
        
        if self.config.ema_smooth_span > 0:
            df_res = df_res.with_columns(
                pl.col("Spread_Raw").ewm_mean(span=self.config.ema_smooth_span, ignore_nulls=True).over("ticker").alias("Spread")
            )
        else:
            df_res = df_res.with_columns(pl.col("Spread_Raw").alias("Spread"))
            
        return (
            df_res
            .select([date_col, "ticker", "price", "return", "VaR", "ES", "Spread_Raw", "Spread"])
            .sort([date_col, "ticker"])
        )

    def calculate_contagion_index(self, df_metrics: pl.DataFrame) -> pl.DataFrame:
        date_col = df_metrics.columns[0]
        return (
            df_metrics
            .with_columns(
                (pl.col("return").is_not_null() & pl.col("VaR").is_not_null()).alias("is_valid")
            )
            .with_columns(
                ((pl.col("return") < pl.col("VaR")) & pl.col("is_valid"))
                .cast(pl.Int32)
                .alias("is_breached")
            )
            .group_by(date_col)
            .agg([
                pl.col("is_breached").sum().alias("Breached_Count"),
                pl.col("is_valid").sum().alias("Valid_Names"),
                pl.len().alias("Total_Names"),
            ])
            .with_columns(
                pl.when(pl.col("Valid_Names") > 0)
                .then(pl.col("Breached_Count") / pl.col("Valid_Names") * 100)
                .otherwise(None)
                .alias("Contagion_Index")
            )
            .sort(date_col)
        )

    def calculate_complacency_index(
        self,
        df_metrics: pl.DataFrame,
        benchmark_ticker: str = None,
    ) -> pl.DataFrame:
        date_col = df_metrics.columns[0]
        
        df = df_metrics.with_columns(
            pl.col("price").rolling_mean(window_size=self.config.trend_ma_window).over("ticker").alias("ma_trend")
        ).with_columns(
            (pl.col("price") > pl.col("ma_trend")).alias("is_uptrend")
        )
        
        tickers = df["ticker"].unique().to_list()
        if benchmark_ticker and benchmark_ticker in tickers:
            proxy_df = (
                df
                .filter(pl.col("ticker") == benchmark_ticker)
                .select([date_col, pl.col("price").alias("market_proxy")])
                .sort(date_col)
            )
            df = df.filter(pl.col("ticker") != benchmark_ticker)
        else:
            base_price = (
                df
                .filter(pl.col("price").is_not_null() & (pl.col("price") > 0))
                .group_by("ticker")
                .agg(pl.col("price").first().alias("base_price"))
            )
            proxy_df = (
                df
                .join(base_price, on="ticker", how="left")
                .with_columns((pl.col("price") / pl.col("base_price")).alias("normalized_price"))
                .group_by(date_col)
                .agg(pl.col("normalized_price").mean().alias("market_proxy"))
                .sort(date_col)
            )
        
        proxy_df = proxy_df.with_columns([
            pl.col("market_proxy").rolling_min(window_size=self.config.pr_window).alias("roll_min"),
            pl.col("market_proxy").rolling_max(window_size=self.config.pr_window).alias("roll_max")
        ])
        
        range_col = pl.col("roll_max") - pl.col("roll_min")
        proxy_df = proxy_df.with_columns(
            pl.when(range_col == 0)
              .then(0.5)
              .otherwise((pl.col("market_proxy") - pl.col("roll_min")) / range_col)
              .clip(0, 1).fill_null(0.5).alias("percent_rank")
        ).with_columns(
            (1.0 + self.config.dynamic_multiplier_base * (1.0 - pl.col("percent_rank"))).alias("multiplier")
        )
        
        # Self-Benchmark: rolling 10th percentile of own Spread
        df = df.with_columns(
            pl.col("Spread")
            .rolling_quantile(0.1, window_size=self.config.pr_window, interpolation="linear")
            .over("ticker")
            .alias("self_baseline_spread_raw")
        ).with_columns(
            pl.col("self_baseline_spread_raw").shift(1).over("ticker").alias("self_baseline_spread")
        )
        
        df = df.join(proxy_df.select([date_col, "multiplier", "percent_rank"]), on=date_col, how="left")
        
        df = df.with_columns(
            (pl.col("self_baseline_spread") * pl.col("multiplier")).alias("dynamic_threshold")
        ).with_columns(
            (
                pl.col("Spread").is_not_null()
                & pl.col("dynamic_threshold").is_not_null()
                & pl.col("is_uptrend").is_not_null()
            ).alias("is_valid_signal")
        ).with_columns(
            pl.when(pl.col("is_valid_signal"))
            .then(((pl.col("Spread") <= pl.col("dynamic_threshold")) & pl.col("is_uptrend")).cast(pl.Int32))
            .otherwise(None)
            .alias("is_mispriced")
        )
        
        return df.sort([date_col, "ticker"])

    def calculate_complacency_aggregate(self, df_complacency: pl.DataFrame) -> pl.DataFrame:
        date_col = df_complacency.columns[0]
        return (
            df_complacency
            .group_by(date_col)
            .agg([
                pl.col("is_mispriced").sum().alias("Mispriced_Count"),
                pl.col("is_valid_signal").sum().alias("Valid_Names"),
                pl.len().alias("Total_Names"),
            ])
            .with_columns(
                pl.when(pl.col("Valid_Names") > 0)
                .then(pl.col("Mispriced_Count") / pl.col("Valid_Names") * 100)
                .otherwise(None)
                .alias("Complacency_Index")
            )
            .sort(date_col)
        )

    def get_latest_risk_status(self, df_complacency: pl.DataFrame) -> pl.DataFrame:
        date_col = df_complacency.columns[0]
        latest_date = df_complacency[date_col].max()
        
        df_latest = df_complacency.filter(pl.col(date_col) == latest_date)
        
        df_latest = df_latest.with_columns(
            pl.when(pl.col("is_mispriced") == 1).then(pl.lit("Risk Mispriced"))
             .otherwise(pl.lit("Bình thường / An toàn"))
             .alias("Status")
        )
        
        df_latest = df_latest.with_columns(
            pl.when(pl.col("is_mispriced") == 1)
             .then(pl.col("dynamic_threshold") - pl.col("Spread"))
             .otherwise(0.0)
             .alias("Severity")
        )
        
        df_latest = df_latest.with_columns(
            pl.when(pl.col("is_mispriced") == 1)
             .then(pl.col("Severity").rank(method="min", descending=True))
             .otherwise(None)
             .alias("Risk_Rank")
        )
        
        df_final = (
            df_latest.select([
                "ticker", "Spread_Raw", "Spread", "dynamic_threshold", 
                "Status", "Severity", "Risk_Rank", "is_valid_signal"
            ])
            .sort(
                by=[
                    pl.col("Risk_Rank").is_null(),
                    "Risk_Rank"
                ],
                descending=[False, False]
            )
        )
        
        return df_final


def classify_vares_regime(
    stress_index_pct: float,
    complacency_index_pct: float,
    stress_alert_pct: float = STRESS_ALERT_PCT,
    complacency_alert_pct: float = COMPLACENCY_ALERT_PCT,
) -> str:
    if np.isfinite(stress_index_pct) and stress_index_pct >= stress_alert_pct:
        return "CONTAGION_ACTIVE"
    if np.isfinite(complacency_index_pct) and complacency_index_pct >= complacency_alert_pct:
        return "COMPLACENCY_DANGER"
    if (
        np.isfinite(stress_index_pct)
        and np.isfinite(complacency_index_pct)
        and stress_index_pct >= stress_alert_pct * 0.5
        and complacency_index_pct >= complacency_alert_pct * 0.5
    ):
        return "LATENT_TAIL_RISK"
    return "NO_VARES_STRESS"


def summarize_vares_state(
    stress_index_pct: float,
    complacency_index_pct: float,
    breached_count: int,
    valid_vn30_count: int,
    mispriced_count: int,
    valid_market_count: int,
) -> dict:
    regime = classify_vares_regime(stress_index_pct, complacency_index_pct)
    if np.isfinite(stress_index_pct) and stress_index_pct >= 60:
        stress_level = "HIGH"
    elif np.isfinite(stress_index_pct) and stress_index_pct >= STRESS_ALERT_PCT:
        stress_level = "ACTIVE"
    elif np.isfinite(stress_index_pct) and stress_index_pct >= 20:
        stress_level = "ELEVATED"
    else:
        stress_level = "LOW"

    if np.isfinite(complacency_index_pct) and complacency_index_pct >= COMPLACENCY_ALERT_PCT:
        complacency_level = "DANGER"
    elif np.isfinite(complacency_index_pct) and complacency_index_pct >= 50:
        complacency_level = "ELEVATED"
    else:
        complacency_level = "LOW"

    return {
        "methodology_version": METHOD_VERSION,
        "vares_regime": regime,
        "stress_level": stress_level,
        "complacency_level": complacency_level,
        "stress_index_pct": float(stress_index_pct),
        "complacency_index_pct": float(complacency_index_pct),
        "breached_count": int(breached_count),
        "valid_vn30_count": int(valid_vn30_count),
        "mispriced_count": int(mispriced_count),
        "valid_market_count": int(valid_market_count),
    }
