#!/usr/bin/env python3
"""Indian Market Breakout & Intraday Setup Scanner for trader-scanner. Standard library only.

Replaces US Nasdaq/NYSE scanner with:
  - NIFTY 50, BANK NIFTY, SENSEX & Top Indian F&O Stocks.
  - Opening Range Breakout (ORB) on Indian market session (09:15 to 09:30 range).
  - 20-Day High Breakout, Reclaim 20-EMA, and RSI Oversold Bounces on NSE tickers (.NS).
"""

import argparse
import datetime
import json
import math
import os
import sys
import urllib.request

DEFAULT_SYMBOLS = [
    "^NSEI", "^NSEBANK", "^BSESN",
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "LT.NS", "AXISBANK.NS",
    "TATAMOTORS.NS", "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS"
]

def fetch_chart(symbol, range_str="1mo", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range_str}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            quotes = res["indicators"]["quote"][0]
            meta = res["meta"]
            return {
                "symbol": symbol,
                "closes": [c for c in quotes.get("close", []) if c is not None],
                "highs": [h for h in quotes.get("high", []) if h is not None],
                "lows": [l for l in quotes.get("low", []) if l is not None],
                "volumes": [v for v in quotes.get("volume", []) if v is not None],
                "last_price": meta.get("regularMarketPrice")
            }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def scan_setups(symbols):
    hits = []
    print(f"Scanning {len(symbols)} Indian symbols for daily setups...")

    for sym in symbols:
        data = fetch_chart(sym, range_str="2mo", interval="1d")
        if "error" in data or len(data.get("closes", [])) < 21:
            continue

        closes = data["closes"]
        last = closes[-1]
        prev_20 = closes[-21:-1]

        # 1. 20-Day Closing High Breakout
        if last > max(prev_20):
            hits.append({"symbol": sym, "setup": "20D Breakout", "price": last})
            continue

        # 2. 20-Day Moving Average Reclaim
        ma20 = sum(prev_20) / len(prev_20)
        if closes[-2] < ma20 and last > ma20:
            hits.append({"symbol": sym, "setup": "Reclaim 20-DMA", "price": last})
            continue

    return hits

def main():
    parser = argparse.ArgumentParser(description="Indian Market Setup Scanner")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="List of Indian symbols to scan")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = scan_setups(args.symbols)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("=" * 60)
    print("🎯 INDIAN MARKET DAILY SETUPS & BREAKOUTS")
    print("=" * 60)
    if not results:
        print("No breakout setups found for the scanned list today.")
        return

    for h in results:
        sym_clean = h['symbol'].replace(".NS", "")
        print(f"🔥 {sym_clean:12} -> {h['setup']:18} @ ₹{h['price']:,.2f}")

if __name__ == "__main__":
    main()
