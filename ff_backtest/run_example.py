import pandas as pd
from backtest import run_backtest

def filter_by_iv(df, top_n=20):
    """
    Filters the DataFrame to include only the top N symbols by mean IV.
    """
    mean_iv = df.groupby('symbol')['iv'].mean().sort_values(ascending=False)
    top_symbols = mean_iv.head(top_n).index
    return df[df['symbol'].isin(top_symbols)]

# Load the full dataset
iv = pd.read_csv("sample_data/iv_snapshots.csv", parse_dates=["date","expiry"])

# Filter for top 20 stocks by IV
iv_filtered = filter_by_iv(iv, top_n=20)


eq, rets = run_backtest(
    iv_df=iv_filtered,
    dte_pair=(30,60),
    min_ff=0.10,
    structure="call_calendar",
    slippage_bps=50,
    commission_per_leg=0.50,
    capital=100000.0,
    risk_per_trade=0.04,
    max_concurrent=10
)

print("Equity (tail):")
print(eq.tail())
print("\nDaily returns (tail):")
print(rets.tail())