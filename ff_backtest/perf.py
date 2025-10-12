import numpy as np
import pandas as pd

def sharpe(returns, rf=0.0, periods_per_year=252):
    r = pd.Series(returns).dropna()
    if len(r)==0: return np.nan
    mu = r.mean()*periods_per_year
    sd = r.std(ddof=0)*np.sqrt(periods_per_year)
    if sd==0: return np.nan
    return float((mu - rf) / sd)

def cagr(equity, periods_per_year=252):
    equity = pd.Series(equity).dropna()
    if len(equity) < 2: return np.nan
    start = equity.iloc[0]
    end = equity.iloc[-1]
    years = len(equity)/periods_per_year
    if start<=0 or years<=0: return np.nan
    return float((end/start)**(1/years) - 1.0)

def max_drawdown(equity):
    equity = pd.Series(equity).dropna()
    if len(equity)==0: return np.nan
    roll_max = equity.cummax()
    dd = equity/roll_max - 1.0
    return float(dd.min())

def summarize(equity_curve, daily_returns):
    return {
        "CAGR": cagr(equity_curve),
        "Sharpe": sharpe(daily_returns),
        "MaxDD": max_drawdown(equity_curve),
        "FinalEquity": float(pd.Series(equity_curve).iloc[-1]) if len(equity_curve)>0 else np.nan
    }
