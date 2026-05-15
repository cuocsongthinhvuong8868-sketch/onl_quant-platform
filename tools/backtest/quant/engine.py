import pandas as pd
import numpy as np

def run_backtest(df_alloc: pd.DataFrame, benchmark_returns: pd.Series, transaction_fee: float = 0.003) -> pd.DataFrame:
    """
    Tầng 3: Backtest Engine.
    Tính toán lợi nhuận dựa trên tỷ lệ phân bổ và phí giao dịch.
    """
    # Đảm bảo index khớp nhau
    common_idx = df_alloc.index.intersection(benchmark_returns.index)
    df = df_alloc.loc[common_idx].copy()
    ret = benchmark_returns.loc[common_idx]

    # Tính Daily Return của Portfolio
    # Portfolio Return = Equity_Weight * Benchmark_Return + Cash_Weight * 0 (Giả định cash return = 0)
    df['strategy_return'] = df['equity_weight'].shift(1) * ret
    
    # Tính Phí giao dịch (khi thay đổi equity_weight)
    df['weight_delta'] = df['equity_weight'].diff().abs()
    df['transaction_cost'] = df['weight_delta'] * transaction_fee
    
    # Lợi nhuận sau phí
    df['net_return'] = df['strategy_return'] - df['transaction_cost'].fillna(0)
    
    # Cumulative returns
    df['cum_strategy'] = (1 + df['net_return']).cumprod()
    df['cum_benchmark'] = (1 + ret).cumprod()
    
    # Drawdown
    df['peak'] = df['cum_strategy'].cummax()
    df['drawdown'] = (df['cum_strategy'] - df['peak']) / df['peak']
    
    return df

def calculate_performance_metrics(df_results: pd.DataFrame) -> dict:
    """
    Tính toán các chỉ số hiệu quả đầu tư.
    """
    net_ret = df_results['net_return'].fillna(0)
    bench_ret = df_results['cum_benchmark'].pct_change().fillna(0)
    
    days = len(df_results)
    years = days / 252
    
    # CAGR
    final_val = df_results['cum_strategy'].iloc[-1]
    cagr = (final_val ** (1/years)) - 1
    
    # Sharpe Ratio (Giả định risk-free = 0)
    vol = net_ret.std() * np.sqrt(252)
    sharpe = (cagr / vol) if vol != 0 else 0
    
    # Max Drawdown
    max_dd = df_results['drawdown'].min()
    
    # Win Rate
    win_rate = (net_ret > 0).sum() / (net_ret != 0).sum()
    
    return {
        "CAGR": cagr,
        "Sharpe": sharpe,
        "Max Drawdown": max_dd,
        "Win Rate": win_rate,
        "Total Return": final_val - 1
    }
