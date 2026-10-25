#!/usr/bin/env python3
"""Indian Market Entry Timing & Bar Watcher for trader-entry. Standard library only.

Watches Indian market 5-minute bars (09:15 to 15:30 IST):
  - 15-minute Opening Range: 09:15, 09:20, and 09:25 bars.
  - Breakout Signal: First 5-minute candle to CLOSE above the opening range high.
  - Entry Window: Active between 09:30 IST and 15:00 IST.
"""

import argparse
import datetime
import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from market_calendar_indian import to_ist, is_market_open

def fetch_5m_bars(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            timestamps = res.get("timestamp", [])
            quotes = res["indicators"]["quote"][0]
            bars = []
            for t, o, h, l, c, v in zip(timestamps, quotes.get("open", []), quotes.get("high", []),
                                       quotes.get("low", []), quotes.get("close", []), quotes.get("volume", [])):
                if None not in (o, h, l, c):
                    dt = datetime.datetime.utcfromtimestamp(t) + datetime.timedelta(hours=5, minutes=30)
                    bars.append({
                        "time": dt.strftime("%H:%M"),
                        "open": o, "high": h, "low": l, "close": c, "volume": v or 0
                    })
            return bars
    except Exception as e:
        return []

def evaluate_orb_entry(symbol):
    now_ist = to_ist()
    mkt_open, msg = is_market_open(now_ist)
    if not mkt_open:
        return {"status": "MARKET_CLOSED", "reason": msg}

    bars = fetch_5m_bars(symbol)
    if len(bars) < 3:
        return {"status": "WAITING", "reason": "Opening range (09:15-09:30 IST) is still forming."}

    # Range bars: first 3 bars (09:15, 09:20, 09:25)
    range_bars = bars[:3]
    or_high = max(b["high"] for b in range_bars)
    or_low = min(b["low"] for b in range_bars)

    # Check breakout in subsequent bars
    for bar in bars[3:]:
        if bar["close"] > or_high:
            return {
                "status": "TRIGGERED",
                "setup": "ORB Breakout",
                "bar_time": bar["time"],
                "trigger_price": bar["close"],
                "or_high": or_high,
                "or_low": or_low,
                "reason": f"Bar at {bar['time']} closed @ ₹{bar['close']:,.2f} above range high ₹{or_high:,.2f}"
            }

    last_close = bars[-1]["close"]
    return {
        "status": "WAITING",
        "or_high": or_high,
        "or_low": or_low,
        "last_price": last_close,
        "reason": f"Trading inside range ({or_low:,.2f} - {or_high:,.2f}). Current: ₹{last_close:,.2f}"
    }

def main():
    parser = argparse.ArgumentParser(description="Indian Market Intraday Entry Watcher")
    parser.add_argument("symbol", default="^NSEI", nargs="?", help="Symbol to check (default: ^NSEI)")
    args = parser.parse_args()

    res = evaluate_orb_entry(args.symbol)

    print("=" * 60)
    print(f"⏱️ INDIAN MARKET ENTRY MONITOR: {args.symbol}")
    print("=" * 60)
    print(f"Status: {res['status']}")
    print(f"Reason: {res['reason']}")
    if "or_high" in res:
        print(f"15m Opening Range: ₹{res['or_low']:,.2f} - ₹{res['or_high']:,.2f}")

if __name__ == "__main__":
    main()
