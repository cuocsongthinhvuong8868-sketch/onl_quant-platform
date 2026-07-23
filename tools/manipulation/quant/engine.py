import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from scipy.stats import percentileofscore

METHOD_VERSION = "manipulation_v2.0.0"
TICKERS = ["VIC", "VHM", "VRE"]
TARGET = "VNINDEX"
TARGET_RETURN_COL = f"{TARGET}_Return"


def _safe_rank_tail(x):
    x = np.asarray(x)
    if len(x) == 0 or np.all(np.isnan(x)):
        return np.nan
    return percentileofscore(x[~np.isnan(x)], x[-1], kind="rank") / 100.0


def prepare_data(df: pd.DataFrame, target_series: pd.Series | None = None) -> pd.DataFrame:
    out = df.copy().sort_index()
    out.index = pd.to_datetime(out.index)

    if target_series is not None:
        target = pd.to_numeric(target_series.sort_index(), errors="coerce")
        target.index = pd.to_datetime(target.index)
        target = target[~target.index.duplicated(keep="last")]
        out = out.join(target.rename(TARGET), how="left")

    req = [*TICKERS, TARGET]
    miss = [c for c in req if c not in out.columns]
    if miss:
        raise ValueError(
            f"Thiếu cột bắt buộc cho Manipulation Detection: {miss}. "
            "Cần VIC/VHM/VRE từ market_data và VNINDEX từ vnindex_cache.csv."
        )

    out = out[[*TICKERS, TARGET]].apply(pd.to_numeric, errors="coerce")
    out = out.dropna(how="all")
    return out


def compute_metrics(df_prices: pd.DataFrame, window: int):
    if len(df_prices) < 2 * window + 10:
        raise ValueError(f"Không đủ dữ liệu cho window={window}. Cần tối thiểu {2 * window + 10} phiên.")

    simple_ret = df_prices.pct_change(fill_method=None)
    simple_ret = simple_ret.mask(simple_ret <= -1.0)
    log_ret = np.log1p(simple_ret).dropna(subset=[*TICKERS, TARGET])

    composite = pd.Series(index=log_ret.index, dtype=float)
    weights = pd.DataFrame(index=log_ret.index, columns=TICKERS, dtype=float)

    pca = PCA(n_components=1)
    for i in range(window, len(log_ret)):
        train = log_ret[TICKERS].iloc[i - window:i]
        pca.fit(train)
        pc1 = pca.components_[0]
        if np.sum(pc1) < 0:
            pc1 = -pc1
        w = np.abs(pc1) / np.sum(np.abs(pc1))
        weights.iloc[i] = w
        composite.iloc[i] = np.dot(w, log_ret[TICKERS].iloc[i])

    comp = composite.dropna()
    target_return = log_ret[TARGET].reindex(comp.index)
    wdf = weights.dropna()

    var_95 = comp.rolling(window).quantile(0.05)

    def cvar_fn(x):
        thr = np.percentile(x, 5)
        tail = x[x <= thr]
        return tail.mean() if len(tail) else np.nan

    cvar_95 = comp.rolling(window).apply(cvar_fn, raw=False)
    corr = comp.rolling(window).corr(target_return)
    slope = comp.rolling(window).cov(target_return) / comp.rolling(window).var()
    intercept = target_return.rolling(window).mean() - slope * comp.rolling(window).mean()

    pr_corr = corr.rolling(window).apply(_safe_rank_tail, raw=True)
    pr_slope = slope.rolling(window).apply(_safe_rank_tail, raw=True)

    result = pd.DataFrame({
        "Composite_Return": comp,
        TARGET_RETURN_COL: target_return,
        "Target_Return": target_return,
        "VaR_95": var_95,
        "CVaR_95": cvar_95,
        "Correlation": corr,
        "OLS_Slope": slope,
        "OLS_Intercept": intercept,
        "PR_Corr": pr_corr,
        "PR_Slope": pr_slope,
    }).dropna(subset=["PR_Corr", "PR_Slope", "Correlation", "OLS_Slope"])

    return wdf, result


def classify_regime(result_df: pd.DataFrame, threshold: float, t0_dt: pd.Timestamp):
    if t0_dt not in result_df.index:
        return None

    base_pr_c = result_df.loc[t0_dt, "PR_Corr"]
    base_pr_s = result_df.loc[t0_dt, "PR_Slope"]
    re_df = result_df.loc[t0_dt:].iloc[1:].copy()
    if re_df.empty:
        return re_df

    re_df["Delta_PR_Corr"] = re_df["PR_Corr"] - base_pr_c
    re_df["Delta_PR_Slope"] = re_df["PR_Slope"] - base_pr_s

    conditions = [
        (re_df["Delta_PR_Corr"] > threshold) & (re_df["Delta_PR_Slope"] > threshold),
        (re_df["Delta_PR_Corr"] > threshold) & (re_df["Delta_PR_Slope"] < -threshold),
        (re_df["Delta_PR_Corr"] < -threshold) & (re_df["Delta_PR_Slope"] < -threshold),
        (re_df["Delta_PR_Corr"] < -threshold) & (re_df["Delta_PR_Slope"] > threshold),
    ]
    choices = ["COUPLING", "ANCHORING", "DECOUPLING", "TÍN HIỆU GIẢ"]
    re_df["Regime"] = np.select(conditions, choices, default="STATUS QUO")
    return re_df
