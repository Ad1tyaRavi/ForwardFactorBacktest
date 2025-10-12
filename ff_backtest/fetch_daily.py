import os, time, math
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from polygon_client import PolygonClient
from fetch_sp500 import get_sp500_tickers

try:
    UNIVERSE = pd.read_csv("sp500_tickers.csv")['ticker'].tolist()
except FileNotFoundError:
    print("sp500_tickers.csv not found, fetching from Wikipedia...")
    tickers = get_sp500_tickers()
    df = pd.DataFrame(tickers, columns=['ticker'])
    df.to_csv('sp500_tickers.csv', index=False)
    print("sp500_tickers.csv created.")
    UNIVERSE = tickers
TARGET_DTES = [(30,60), (60,90)]
DTE_TOL = 3
MAX_PER_MINUTE = 5
OUT_CSV = os.getenv("FF_OUT_CSV", "sample_data/iv_snapshots.csv")

def nearest_dte(expiries: List[datetime], today: datetime, target_dte: int, tol: int) -> Optional[datetime]:
    candidates = []
    for e in expiries:
        dte = (e - today).days
        if abs(dte - target_dte) <= tol and dte > 0:
            candidates.append((abs(dte - target_dte), e))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]

def pick_atm_row(rows: List[Dict[str, Any]], spot: float, is_call: bool) -> Optional[Dict[str, Any]]:
    atm = None; best = 1e18
    for r in rows:
        if bool(r.get("contract_type") == "call") != is_call:
            continue
        k = float(r.get("strike_price"))
        diff = abs(k - spot)
        if diff < best:
            best = diff; atm = r
    return atm

def extract_mid_bidask(r: Dict[str, Any]):
    bid = r.get("bid", r.get("last_quote", {}).get("P"))
    ask = r.get("ask", r.get("last_quote", {}).get("p"))
    mid = None
    try:
        if bid is not None and ask is not None:
            bid = float(bid); ask = float(ask)
            if bid>0 and ask>0: mid = 0.5*(bid+ask)
    except Exception: pass
    if mid is None:
        last = r.get("price", r.get("last_trade", {}).get("p"))
        mid = float(last) if last is not None else None
    return (float(bid) if bid is not None else None,
            float(ask) if ask is not None else None,
            float(mid) if mid is not None else None)

def extract_iv(r: Dict[str, Any]) -> Optional[float]:
    iv = r.get("implied_volatility") or r.get("greeks", {}).get("iv")
    if iv is None: return None
    try:
        iv = float(iv); return iv if iv>0 else None
    except Exception: return None

def forward_variance(sig1: float, sig2: float, T1y: float, T2y: float) -> Optional[float]:
    if T2y <= T1y: return None
    v1, v2 = sig1*sig1, sig2*sig2
    fv = (T2y*v2 - T1y*v1)/(T2y - T1y)
    return fv if fv and fv>0 else None

def forward_factor(sig_front: float, sig_fwd: float) -> Optional[float]:
    if not sig_fwd or sig_fwd<=0: return None
    return (sig_front - sig_fwd)/sig_fwd

def snapshot_to_rows(pc: PolygonClient, symbol: str, today: datetime) -> List[Dict[str, Any]]:
    snap = pc.snapshot_option_chain(symbol)
    prev = pc.previous_close(symbol)
    spot = prev
    if isinstance(snap, dict):
        u = snap.get("underlying_asset") or snap.get("underlying")
        if isinstance(u, dict):
            spot = u.get("price") or spot
    if spot is None: return []

    chain = snap.get("results") or snap.get("options") or []
    by_exp = {}; expiries = []
    for r in chain:
        exp = r.get("expiration_date") or r.get("details", {}).get("expiration_date")
        if not exp: continue
        exp_dt = datetime.fromisoformat(exp.replace("Z","")) if "T" in exp else datetime.strptime(exp[:10], "%Y-%m-%d")
        expiries.append(exp_dt); by_exp.setdefault(exp_dt.isoformat(), []).append(r)

    rows_out = []
    for (t1, t2) in TARGET_DTES:
        near = nearest_dte(expiries, today, t1, DTE_TOL)
        far  = nearest_dte(expiries, today, t2, DTE_TOL)
        if not near or not far: continue
        near_rows = by_exp.get(near.isoformat(), [])
        far_rows  = by_exp.get(far.isoformat(), [])
        n_call = pick_atm_row(near_rows, float(spot), True)
        f_call = pick_atm_row(far_rows, float(spot), True)
        n_put  = pick_atm_row(near_rows, float(spot), False)
        f_put  = pick_atm_row(far_rows, float(spot), False)
        if n_call is None or f_call is None: continue

        iv1 = extract_iv(n_call); iv2 = extract_iv(f_call)
        sig_fwd = None; FF = None
        dte1 = (near - today).days; dte2 = (far - today).days
        if iv1 and iv2:
            fv = forward_variance(iv1, iv2, dte1/365.0, dte2/365.0)
            if fv:
                sig_fwd = math.sqrt(fv)
                FF = forward_factor(iv1, sig_fwd)

        for leg, exp, src in [("near_call", near, n_call), ("far_call", far, f_call),
                              ("near_put", near, n_put) if n_put else (None,None,None),
                              ("far_put",  far,  f_put) if f_put else (None,None,None)]:
            if leg is None or src is None: continue
            bid, ask, mid = extract_mid_bidask(src)
            strike = float(src.get("strike_price"))
            is_call = (src.get("contract_type")=="call")
            rows_out.append({
                "date": today.date().isoformat(),
                "symbol": symbol,
                "expiry": exp.date().isoformat(),
                "dte": (exp - today).days,
                "iv": iv1 if leg in ("near_call","near_put") else iv2 if leg in ("far_call","far_put") else None,
                "bid": bid, "ask": ask, "mid": mid,
                "underlying": float(spot),
                "oi": src.get("open_interest"),
                "volume": src.get("volume"),
                "is_call": is_call,
                "strike": strike,
                "sig_fwd": sig_fwd if sig_fwd is not None else float("nan"),
                "FF": FF if FF is not None else float("nan")
            })
    return rows_out

def main():
    pc = PolygonClient()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    all_rows = []; calls = 0
    for sym in UNIVERSE:
        sym = sym.strip().upper()
        if not sym: continue
        if calls and (calls % MAX_PER_MINUTE == 0):
            time.sleep(60)
        try:
            rows = snapshot_to_rows(pc, sym, today)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[WARN] {sym}: {e}")
        calls += 1
    if not all_rows:
        print("No rows fetched."); return
    df = pd.DataFrame(all_rows)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    if os.path.exists(OUT_CSV):
        prev = pd.read_csv(OUT_CSV)
        combined = pd.concat([prev, df], ignore_index=True)
        combined.drop_duplicates(subset=["date", "symbol", "expiry", "is_call", "strike"], inplace=True)
        combined.sort_values(["date", "symbol", "expiry", "is_call", "strike"], inplace=True)
        combined.to_csv(OUT_CSV, index=False)
        print(f"Appended {len(df)} rows (total {len(combined)}) to {OUT_CSV}")
    else:
        df.sort_values(["date", "symbol", "expiry", "is_call", "strike"], inplace=True)
        df.to_csv(OUT_CSV, index=False)
        print(f"Wrote {len(df)} rows to {OUT_CSV}")

if __name__ == "__main__":
    main()
