import os, math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from alphavantage_client import AlphaVantageClient
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
    atm = None
    best = float("inf")
    for r in rows:
        strike = extract_strike(r)
        if strike is None:
            continue
        diff = abs(strike - spot)
        if diff < best:
            best = diff
            atm = r
    return atm

def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None
    return None

def extract_strike(row: Dict[str, Any]) -> Optional[float]:
    for key in ("strike", "strikePrice", "strike_price"):
        strike = parse_float(row.get(key))
        if strike is not None:
            return strike
    return None

def extract_mid_bidask(r: Dict[str, Any]):
    bid = None
    ask = None
    for key in ("bid", "bidPrice", "bid_price"):
        bid = parse_float(r.get(key))
        if bid is not None:
            break
    for key in ("ask", "askPrice", "ask_price"):
        ask = parse_float(r.get(key))
        if ask is not None:
            break

    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = 0.5 * (bid + ask)
    else:
        for key in ("last", "lastPrice", "price"):
            mid = parse_float(r.get(key))
            if mid is not None:
                break

    return bid, ask, mid

def extract_iv(r: Dict[str, Any]) -> Optional[float]:
    iv = None
    for key in ("impliedVolatility", "implied_volatility", "iv"):
        iv = parse_float(r.get(key))
        if iv is not None:
            break
    if iv is None or iv <= 0:
        return None
    return iv

def forward_variance(sig1: float, sig2: float, T1y: float, T2y: float) -> Optional[float]:
    if T2y <= T1y: return None
    v1, v2 = sig1*sig1, sig2*sig2
    fv = (T2y*v2 - T1y*v1)/(T2y - T1y)
    return fv if fv and fv>0 else None

def forward_factor(sig_front: float, sig_fwd: float) -> Optional[float]:
    if not sig_fwd or sig_fwd<=0: return None
    return (sig_front - sig_fwd)/sig_fwd

def parse_expiration(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Treat numeric timestamps as UNIX seconds.
        try:
            return datetime.utcfromtimestamp(float(value))
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text[: len(fmt)], fmt)
            return dt
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None

def resolve_contract_type(row: Dict[str, Any]) -> Optional[bool]:
    flag = row.get("contractType") or row.get("contract_type") or row.get("optionType") or row.get("option_type") or row.get("type")
    if flag is None:
        return None
    text = str(flag).strip().lower()
    if text in ("call", "calls", "c"):
        return True
    if text in ("put", "puts", "p"):
        return False
    return None

def iter_option_entries(chain: Any) -> List[Tuple[Optional[datetime], Optional[bool], Dict[str, Any]]]:
    entries: List[Tuple[Optional[datetime], Optional[bool], Dict[str, Any]]] = []
    if isinstance(chain, list):
        for item in chain:
            expiry_hint = parse_expiration(
                item.get("expiration")
                or item.get("expirationDate")
                or item.get("expiry")
                or item.get("expiryDate")
            )
            calls = item.get("calls")
            puts = item.get("puts")
            if isinstance(calls, list) or isinstance(puts, list):
                if isinstance(calls, list):
                    for row in calls:
                        exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or expiry_hint
                        entries.append((exp, True, row))
                if isinstance(puts, list):
                    for row in puts:
                        exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or expiry_hint
                        entries.append((exp, False, row))
            else:
                entries.append((expiry_hint, resolve_contract_type(item), item))
    elif isinstance(chain, dict):
        if any(k in chain for k in ("calls", "puts")):
            expiry_hint = parse_expiration(
                chain.get("expiration") or chain.get("expirationDate")
            )
            calls = chain.get("calls")
            puts = chain.get("puts")
            if isinstance(calls, list):
                for row in calls:
                    exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or expiry_hint
                    entries.append((exp, True, row))
            if isinstance(puts, list):
                for row in puts:
                    exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or expiry_hint
                    entries.append((exp, False, row))
        else:
            for key, value in chain.items():
                expiry_hint = parse_expiration(key)
                if isinstance(value, dict) and any(k in value for k in ("calls", "puts")):
                    calls = value.get("calls")
                    puts = value.get("puts")
                    exp_override = parse_expiration(value.get("expiration") or value.get("expirationDate")) or expiry_hint
                    if isinstance(calls, list):
                        for row in calls:
                            exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or exp_override
                            entries.append((exp, True, row))
                    if isinstance(puts, list):
                        for row in puts:
                            exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or exp_override
                            entries.append((exp, False, row))
                elif isinstance(value, list):
                    for row in value:
                        exp = parse_expiration(row.get("expiration") or row.get("expirationDate")) or expiry_hint
                        entries.append((exp, resolve_contract_type(row), row))
                elif isinstance(value, dict):
                    entries.append((expiry_hint, resolve_contract_type(value), value))
    return entries

def parse_quote_price(data: Dict[str, Any]) -> Optional[float]:
    quote = data.get("Global Quote") or data.get("globalQuote") or {}
    for key in ("05. price", "05. Price", "price", "regularMarketPrice", "close"):
        price = parse_float(quote.get(key) or data.get(key))
        if price is not None:
            return price
    return None

def snapshot_to_rows(client: AlphaVantageClient, symbol: str, today: datetime) -> List[Dict[str, Any]]:
    chain_resp = client.option_chain(symbol)
    spot = parse_quote_price(client.global_quote(symbol))
    if spot is None:
        return []

    raw_chain = (
        chain_resp.get("option_chain")
        or chain_resp.get("optionChain")
        or chain_resp.get("data")
        or chain_resp
    )
    entries = iter_option_entries(raw_chain)
    if not entries:
        return []

    by_exp: Dict[datetime, Dict[str, List[Dict[str, Any]]]] = {}
    expiries: List[datetime] = []
    for expiry, is_call, payload in entries:
        expiry = expiry or parse_expiration(
            payload.get("expiration") or payload.get("expirationDate")
        )
        if expiry is None:
            continue
        expiry = expiry.replace(hour=0, minute=0, second=0, microsecond=0)
        bucket = by_exp.setdefault(expiry, {"calls": [], "puts": []})
        call_flag = is_call if is_call is not None else resolve_contract_type(payload)
        if call_flag is None:
            continue
        bucket["calls" if call_flag else "puts"].append(payload)
        expiries.append(expiry)

    if not by_exp:
        return []

    rows_out = []
    for (t1, t2) in TARGET_DTES:
        near = nearest_dte(expiries, today, t1, DTE_TOL)
        far  = nearest_dte(expiries, today, t2, DTE_TOL)
        if not near or not far:
            continue
        near_rows = by_exp.get(near, {"calls": [], "puts": []})
        far_rows  = by_exp.get(far, {"calls": [], "puts": []})
        n_call = pick_atm_row(near_rows.get("calls", []), float(spot), True)
        f_call = pick_atm_row(far_rows.get("calls", []), float(spot), True)
        n_put  = pick_atm_row(near_rows.get("puts", []), float(spot), False)
        f_put  = pick_atm_row(far_rows.get("puts", []), float(spot), False)
        if n_call is None or f_call is None:
            continue

        iv1 = extract_iv(n_call)
        iv2 = extract_iv(f_call)
        sig_fwd = None
        FF = None
        dte1 = (near - today).days
        dte2 = (far - today).days
        if iv1 and iv2:
            fv = forward_variance(iv1, iv2, dte1/365.0, dte2/365.0)
            if fv:
                sig_fwd = math.sqrt(fv)
                FF = forward_factor(iv1, sig_fwd)

        for leg, exp, src in [
            ("near_call", near, n_call),
            ("far_call", far, f_call),
            ("near_put", near, n_put) if n_put else (None, None, None),
            ("far_put", far, f_put) if f_put else (None, None, None),
        ]:
            if leg is None or src is None:
                continue
            bid, ask, mid = extract_mid_bidask(src)
            strike = extract_strike(src)
            if strike is None:
                continue
            rows_out.append({
                "date": today.date().isoformat(),
                "symbol": symbol,
                "expiry": exp.date().isoformat(),
                "dte": (exp - today).days,
                "iv": iv1 if leg in ("near_call", "near_put") else iv2 if leg in ("far_call", "far_put") else None,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "underlying": float(spot),
                "oi": parse_float(src.get("openInterest") or src.get("open_interest")),
                "volume": parse_float(src.get("volume")),
                "is_call": leg in ("near_call", "far_call"),
                "strike": strike,
                "sig_fwd": sig_fwd if sig_fwd is not None else float("nan"),
                "FF": FF if FF is not None else float("nan"),
            })
    return rows_out

def main():
    client = AlphaVantageClient()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    all_rows: List[Dict[str, Any]] = []
    for sym in UNIVERSE:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            rows = snapshot_to_rows(client, sym, today)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[WARN] {sym}: {e}")
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
