#!/usr/bin/env python3
"""Indian Market Price Alerts & NSE Clock for trader-alerts. Standard library only.

Replaces US NYSE clock & alerts with:
  - Official NSE/BSE Market Clock (09:15 to 15:30 IST)
  - Intraday Square-Off Alert at 15:15 IST
  - Quotes and price triggers for NIFTY, BANK NIFTY, SENSEX, and Indian F&O stocks
"""

import argparse
import datetime
import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from market_calendar_indian import to_ist, is_market_open, next_market_open, SQUARE_OFF_TIME

INDEX_TOKENS = {
    "NIFTY": ("NSE", "99926000", "^NSEI"),
    "BANKNIFTY": ("NSE", "99926009", "^NSEBANK"),
    "SENSEX": ("BSE", "99919000", "^BSESN")
}

def get_quote_yahoo(symbol):
    """Fetches quote for Indian index or stock (.NS) via Yahoo v8 endpoint"""
    clean_sym = symbol.upper()
    if clean_sym in INDEX_TOKENS:
        yahoo_sym = INDEX_TOKENS[clean_sym][2]
    elif not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO"):
        yahoo_sym = f"{clean_sym}.NS"
    else:
        yahoo_sym = clean_sym

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?range=1d&interval=1m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            return {
                "symbol": clean_sym,
                "price": meta.get("regularMarketPrice"),
                "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
                "exchange": meta.get("exchangeName"),
                "time": meta.get("regularMarketTime")
            }
    except Exception as e:
        return {"symbol": clean_sym, "error": str(e)}

def print_clock():
    now_ist = to_ist()
    status, reason = is_market_open(now_ist)
    print("=" * 60)
    print("🕒 NSE / BSE INDIAN MARKET CLOCK")
    print("=" * 60)
    print(f"Current IST:        {now_ist.strftime('%d-%b-%Y %H:%M:%S')} IST")
    print(f"Market Status:      {'🟢 OPEN' if status else '🔴 CLOSED'} ({reason})")
    print(f"Trading Hours:      09:15 - 15:30 IST")
    print(f"Auto Square-Off:    15:15 IST")
    if not status:
        nxt = next_market_open(now_ist)
        print(f"Next Market Open:   {nxt.strftime('%d-%b-%Y %H:%M')} IST")

def main():
    parser = argparse.ArgumentParser(description="Indian Market Price Alerts & Clock")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("clock", help="Check NSE/BSE market status and trading hours")
    
    qp = sub.add_parser("quote", help="Get live quote for Indian symbols")
    qp.add_argument("symbols", nargs="+", help="Tickers (e.g. NIFTY, BANKNIFTY, RELIANCE, TCS)")

    args = parser.parse_args()

    if args.command == "clock" or not args.command:
        print_clock()
    elif args.command == "quote":
        print("=" * 60)
        print("📈 INDIAN MARKET LIVE QUOTES")
        print("=" * 60)
        for sym in args.symbols:
            q = get_quote_yahoo(sym)
            if "error" in q:
                print(f"⚠️ {sym:12}: {q['error']}")
            else:
                price = q.get("price")
                prev = q.get("prev_close")
                change = (price - prev) if (price and prev) else 0
                pct = (change / prev * 100) if prev else 0
                sign = "+" if change >= 0 else ""
                print(f"• {sym:12}: ₹{price:,.2f} ({sign}{change:.2f}, {sign}{pct:.2f}%)")

if __name__ == "__main__":
    main()
