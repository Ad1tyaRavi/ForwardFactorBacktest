import numpy as np
import pandas as pd

def ex_earnings_filter(trades_df: pd.DataFrame, earnings_df: pd.DataFrame) -> pd.DataFrame:
    if earnings_df is None or earnings_df.empty:
        return trades_df.copy()
    merged = trades_df.merge(earnings_df, on="symbol", how="left")
    keep = (merged["earn_date"].isna()) | ((merged["earn_date"] < merged["entry_date"]) | (merged["earn_date"] > merged["exit_date"]))
    return merged.loc[keep, trades_df.columns]

def liquidity_filter(df, min_oi=200, min_vol=500, max_spread_bps=300):
    df = df.copy()
    spr = (df["ask"] - df["bid"]).clip(lower=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        spr_bps = np.where(df["mid"]>0, 10000.0*spr/df["mid"], np.inf)
    ok = (df["oi"] >= min_oi) & (df["volume"] >= min_vol) & (spr_bps <= max_spread_bps)
    return df.loc[ok]

def zscore(series, window=252):
    x = series.astype(float)
    mu = x.rolling(window).mean()
    sd = x.rolling(window).std(ddof=0)
    return (x - mu) / sd

def realized_vol_filter(df, rv_col="rv_21", sig_fwd_col="sig_fwd", min_gap=0.0):
    if rv_col not in df.columns or sig_fwd_col not in df.columns:
        return df
    return df.loc[(df[sig_fwd_col] < df[rv_col]*(1.0 - min_gap))]
