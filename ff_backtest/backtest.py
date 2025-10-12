import numpy as np
import pandas as pd
from factors import forward_vol, forward_factor, annualized_days

def pick_atm(snapshot, underlying_price):
    if snapshot.empty:
        return None, None
    atm_strike = snapshot.iloc[(snapshot["strike"]-underlying_price).abs().argsort()].iloc[0]["strike"]
    call = snapshot[(snapshot["strike"]==atm_strike) & (snapshot["is_call"]==True)]
    put  = snapshot[(snapshot["strike"]==atm_strike) & (snapshot["is_call"]==False)]
    call_row = call.iloc[0] if len(call)>0 else None
    put_row  = put.iloc[0] if len(put)>0 else None
    return call_row, put_row

def compute_ff(sig_front, sig_back, T1_days, T2_days):
    T1y, T2y = annualized_days(T1_days), annualized_days(T2_days)
    sig_fwd = forward_vol(sig_front, sig_back, T1y, T2y)
    if sig_fwd is None or np.isnan(sig_fwd):
        return np.nan, np.nan
    FF = forward_factor(sig_front, sig_fwd)
    return sig_fwd, FF

def simulate_calendar_price(front_leg_mid, back_leg_mid):
    return float(back_leg_mid - front_leg_mid)

def run_backtest(iv_df, 
                 dte_pair=(30,60),
                 min_ff=0.20,
                 structure="call_calendar",
                 slippage_bps=50,
                 commission_per_leg=0.50,
                 capital=100000.0,
                 risk_per_trade=0.04,
                 max_concurrent=20):

    iv_df = iv_df.copy()
    iv_df["date"] = pd.to_datetime(iv_df["date"])
    iv_df["expiry"] = pd.to_datetime(iv_df["expiry"])
    iv_df = iv_df.sort_values(["date","symbol","expiry","is_call","strike"])

    dates = sorted(iv_df["date"].unique())
    if not iv_df.empty:
        max_expiry = iv_df["expiry"].max()
        if pd.notna(max_expiry):
            start_date = min(dates) if dates else pd.Timestamp.now()
            all_dates = pd.date_range(start=start_date, end=max_expiry, freq='B')
            dates = sorted(list(set(dates).union(set(all_dates))))

    cash = capital
    equity_curve = []
    daily_returns = []
    open_trades = []

    def get_chain(day, sym, exp):
        snap = iv_df[(iv_df["date"]==day) & (iv_df["symbol"]==sym) & (iv_df["expiry"]==exp)]
        return snap.copy()

    def close_due_trades(today):
        nonlocal cash, open_trades
        ret_today = 0.0
        still = []
        for tr in open_trades:
            if today >= tr["exit_date"]:
                near_snap = get_chain(today, tr["symbol"], tr["near_exp"])
                far_snap  = get_chain(today, tr["symbol"], tr["far_exp"])
                if near_snap.empty or far_snap.empty:
                    # Assume total loss if data is not available for closing the trade
                    pnl = -tr["entry_debit"]
                    cash += tr["n_spreads"] * pnl
                    ret_today += (tr["n_spreads"] * pnl) / max(capital, 1e-9)
                    continue # trade is closed
                und = near_snap["underlying"].iloc[0]
                n_call, n_put = pick_atm(near_snap, und)
                f_call, f_put = pick_atm(far_snap, und)
                if n_call is None or f_call is None:
                    still.append(tr); continue

                if tr["structure"]=="call_calendar":
                    exit_price = simulate_calendar_price(n_call["mid"], f_call["mid"])
                    legs = 2
                else:
                    if n_put is None or f_put is None:
                        still.append(tr); continue
                    exit_price = simulate_calendar_price(n_call["mid"], f_call["mid"]) + simulate_calendar_price(n_put["mid"], f_put["mid"])
                    legs = 4

                exit_price = exit_price * (1.0 - slippage_bps/10000.0) - legs*commission_per_leg
                pnl = (exit_price - tr["entry_debit"])
                cash += tr["n_spreads"] * pnl
                ret_today += (tr["n_spreads"] * pnl) / max(capital, 1e-9)
            else:
                still.append(tr)
        open_trades = still
        return ret_today

    for d in dates:
        ret_t = close_due_trades(d)
        print(f"Date: {d}, Return: {ret_t}")
        daily_returns.append(ret_t)

        if len(open_trades) < max_concurrent:
            T1, T2 = dte_pair
            todays = iv_df[iv_df["date"]==d]
            near = todays[todays["dte"].between(T1-3, T1+3)]
            far  = todays[todays["dte"].between(T2-3, T2+3)]
            syms = sorted(set(near["symbol"]).intersection(set(far["symbol"])))
            cands = []
            for sym in syms:
                near_chain = near[near["symbol"]==sym]
                far_chain  = far[far["symbol"]==sym]
                if near_chain.empty or far_chain.empty: 
                    continue
                und = near_chain["underlying"].iloc[0]
                n_call, n_put = pick_atm(near_chain, und)
                f_call, f_put = pick_atm(far_chain, und)
                if n_call is None or f_call is None:
                    continue
                sig_front = n_call["iv"]
                sig_back  = f_call["iv"]
                sig_fwd, FF = compute_ff(sig_front, sig_back, T1, T2)
                if np.isnan(FF) or FF < min_ff:
                    continue

                if structure=="call_calendar":
                    entry_debit = (f_call["mid"] - n_call["mid"])
                    legs = 2
                else:
                    if (n_put is None) or (f_put is None):
                        continue
                    entry_debit = (f_call["mid"] - n_call["mid"]) + (f_put["mid"] - n_put["mid"])
                    legs = 4

                entry_debit = entry_debit * (1.0 + slippage_bps/10000.0) + legs*commission_per_leg
                if entry_debit <= 0: 
                    continue

                cands.append({
                    "symbol": sym,
                    "near_exp": pd.to_datetime(n_call["expiry"]),
                    "far_exp": pd.to_datetime(f_call["expiry"]),
                    "entry_date": d,
                    "exit_date": pd.to_datetime(n_call["expiry"]),
                    "FF": float(FF),
                    "sig_fwd": float(sig_fwd),
                    "entry_debit": float(entry_debit),
                    "structure": structure
                })

            cands = sorted(cands, key=lambda x: x["FF"], reverse=True)
            slots = max_concurrent - len(open_trades)
            for tr in cands[:slots]:
                alloc = max(0.0, cash * risk_per_trade)
                price = tr["entry_debit"]
                n_spreads = int(alloc // price)
                if n_spreads <= 0:
                    continue
                cash -= n_spreads * price
                tr["n_spreads"] = n_spreads
                open_trades.append(tr)

        equity_curve.append(cash)

    eq = pd.Series(equity_curve, index=dates).ffill()
    rets = pd.Series(daily_returns, index=dates).fillna(0.0)
    return eq, rets
