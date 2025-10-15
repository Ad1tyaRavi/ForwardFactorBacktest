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

def _leg_price(mid: float, slippage_bps: float, side: str) -> float:
    """Apply slippage to a leg depending on whether we are buying or selling."""
    if mid is None or np.isnan(mid):
        return np.nan
    slip = slippage_bps / 10000.0
    if side == "buy":
        return float(mid * (1.0 + slip))
    return float(mid * (1.0 - slip))


def _calendar_mid(structure, n_call, f_call, n_put, f_put):
    """Return the mid-price of the calendar structure without costs."""
    if structure == "call_calendar":
        return float(f_call["mid"] - n_call["mid"])
    if n_put is None or f_put is None:
        return np.nan
    return float((f_call["mid"] - n_call["mid"]) + (f_put["mid"] - n_put["mid"]))


def _trade_price(structure, n_call, f_call, n_put, f_put, slippage_bps, commission_per_leg, action):
    """
    Approximate the executable price for opening or closing a calendar.
    `action` should be either "open" (debit) or "close" (credit).
    """
    slip_side_open = {
        "open": {"far": "buy", "near": "sell"},
        "close": {"far": "sell", "near": "buy"},
    }
    sides = slip_side_open.get(action)
    if sides is None:
        raise ValueError(f"Unsupported action '{action}'")

    def call_price(n, f):
        far_px = _leg_price(f["mid"], slippage_bps, sides["far"])
        near_px = _leg_price(n["mid"], slippage_bps, sides["near"])
        if np.isnan(far_px) or np.isnan(near_px):
            return np.nan
        return far_px - near_px

    if structure == "call_calendar":
        base = call_price(n_call, f_call)
        legs = 2
    else:
        if n_put is None or f_put is None:
            return np.nan
        call_component = call_price(n_call, f_call)
        buy_far_put = _leg_price(f_put["mid"], slippage_bps, sides["far"])
        sell_near_put = _leg_price(n_put["mid"], slippage_bps, sides["near"])
        if np.isnan(call_component) or np.isnan(buy_far_put) or np.isnan(sell_near_put):
            return np.nan
        base = call_component + (buy_far_put - sell_near_put)
        legs = 4

    commission = legs * commission_per_leg
    if action == "open":
        return float(base + commission)
    return float(base - commission)

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

    def price_trade_mid(trade, day):
        near_snap = get_chain(day, trade["symbol"], trade["near_exp"])
        far_snap = get_chain(day, trade["symbol"], trade["far_exp"])
        if near_snap.empty or far_snap.empty:
            return trade.get("last_mid", trade["entry_mid"])
        und = near_snap["underlying"].iloc[0]
        n_call, n_put = pick_atm(near_snap, und)
        f_call, f_put = pick_atm(far_snap, und)
        if n_call is None or f_call is None:
            return trade.get("last_mid", trade["entry_mid"])
        mid = _calendar_mid(trade["structure"], n_call, f_call, n_put, f_put)
        if np.isnan(mid):
            return trade.get("last_mid", trade["entry_mid"])
        return float(mid)

    def mark_to_market(today):
        total = 0.0
        for tr in open_trades:
            price = price_trade_mid(tr, today)
            tr["last_mid"] = price
            total += tr["n_spreads"] * price
        return total

    def close_due_trades(today):
        nonlocal cash, open_trades
        still = []
        for tr in open_trades:
            if today >= tr["exit_date"]:
                near_snap = get_chain(today, tr["symbol"], tr["near_exp"])
                far_snap  = get_chain(today, tr["symbol"], tr["far_exp"])
                if near_snap.empty or far_snap.empty:
                    still.append(tr)
                    continue
                und = near_snap["underlying"].iloc[0]
                n_call, n_put = pick_atm(near_snap, und)
                f_call, f_put = pick_atm(far_snap, und)
                if n_call is None or f_call is None:
                    still.append(tr); continue
                exit_mid = _calendar_mid(tr["structure"], n_call, f_call, n_put, f_put)
                exit_price = _trade_price(tr["structure"], n_call, f_call, n_put, f_put,
                                          slippage_bps, commission_per_leg, action="close")
                if np.isnan(exit_mid) or np.isnan(exit_price):
                    still.append(tr); continue

                pnl = (exit_price - tr["entry_debit"])
                cash += tr["n_spreads"] * exit_price
            else:
                still.append(tr)
        open_trades = still
        return

    for d in dates:
        close_due_trades(d)

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

                if structure != "call_calendar" and ((n_put is None) or (f_put is None)):
                    continue

                entry_mid = _calendar_mid(structure, n_call, f_call, n_put, f_put)
                entry_debit = _trade_price(structure, n_call, f_call, n_put, f_put,
                                           slippage_bps, commission_per_leg, action="open")

                if np.isnan(entry_mid) or np.isnan(entry_debit) or entry_mid <= 0 or entry_debit <= 0:
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
                    "entry_mid": float(entry_mid),
                    "structure": structure,
                    "legs": 2 if structure == "call_calendar" else 4
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
                tr["last_mid"] = tr["entry_mid"]
                open_trades.append(tr)

        mtm = mark_to_market(d)
        equity = cash + mtm
        prev_equity = equity_curve[-1] if equity_curve else capital
        equity_curve.append(equity)
        baseline = prev_equity if abs(prev_equity) > 1e-9 else capital
        daily_returns.append((equity - prev_equity) / max(baseline, 1e-9))

    eq = pd.Series(equity_curve, index=dates).ffill()
    rets = pd.Series(daily_returns, index=dates).fillna(0.0)
    return eq, rets
