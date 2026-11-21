#!/usr/bin/env python3
"""Indian Market Entry Timing & Bar Watcher for trader-entry. Standard library only.

Watches Indian market 5-minute bars (09:15 to 15:30 IST):
  - 15-minute Opening Range: the 09:15, 09:20 and 09:25 bars (all three required).
  - Breakout Signal: first COMPLETED 5-minute candle to close above the range
    high (long) or below the range low (short).
  - Entry Window: bars from 09:30 IST up to the last-entry time (15:00 by default).

The same rule is replayed over history by trader-timemachine/backtest_indian.py,
so what the watcher signals is exactly what the backtest measured.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from market_calendar_indian import to_ist, is_market_open

BAR_MINUTES = 5
RANGE_START = "09:15"
RANGE_END = "09:30"
RANGE_BARS = 3
IST = datetime.timedelta(hours=5, minutes=30)


def parse_chart(data):
    """Yahoo chart JSON -> list of bars with IST date and time, oldest first."""
    res = data["chart"]["result"][0]
    timestamps = res.get("timestamp") or []
    quotes = res["indicators"]["quote"][0]
    bars = []
    for t, o, h, l, c, v in zip(timestamps, quotes.get("open", []), quotes.get("high", []),
                                quotes.get("low", []), quotes.get("close", []), quotes.get("volume", [])):
        if None in (o, h, l, c):
            continue
        dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None) + IST
        if dt.minute % BAR_MINUTES or dt.second:
            continue  # Yahoo appends a "right now" tick that is not a real bar
        bars.append({"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
                     "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    return bars


def fetch_5m_bars(symbol, range_str="1d"):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=5m" % (
        urllib.parse.quote(symbol), range_str)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return parse_chart(json.loads(resp.read().decode("utf-8")))


def completed_bars(bars, now_ist):
    """Drop the bar that is still forming: a signal needs a bar that has closed."""
    done = []
    for bar in bars:
        start = datetime.datetime.strptime(bar["date"] + " " + bar["time"], "%Y-%m-%d %H:%M")
        if start + datetime.timedelta(minutes=BAR_MINUTES) <= now_ist:
            done.append(bar)
    return done


def opening_range(day_bars):
    """(high, low) of the 09:15-09:30 range, or None unless all three bars are there."""
    rng = [b for b in day_bars if RANGE_START <= b["time"] < RANGE_END]
    if len(rng) < RANGE_BARS:
        return None
    return max(b["high"] for b in rng), min(b["low"] for b in rng)


def first_breakout(day_bars, direction="both", last_entry="15:00"):
    """First bar after the range that closes outside it.

    Returns (index into day_bars, "long" or "short"), or None. Only the first
    break of the day counts: a later break the other way is not a fresh signal.
    """
    rng = opening_range(day_bars)
    if rng is None:
        return None
    or_high, or_low = rng
    for i, bar in enumerate(day_bars):
        if bar["time"] < RANGE_END:
            continue
        if bar["time"] > last_entry:
            return None
        if bar["close"] > or_high:
            return (i, "long") if direction in ("long", "both") else None
        if bar["close"] < or_low:
            return (i, "short") if direction in ("short", "both") else None
    return None


def evaluate_orb_entry(symbol, direction="both", now_ist=None, bars=None):
    now_ist = now_ist or to_ist()
    mkt_open, msg = is_market_open(now_ist)
    if not mkt_open:
        return {"status": "MARKET_CLOSED", "reason": msg}

    if bars is None:
        try:
            bars = fetch_5m_bars(symbol)
        except Exception as exc:  # network trouble or an unexpected reply
            return {"status": "NO_DATA", "reason": "Could not read 5-minute bars for %s: %s" % (symbol, exc)}

    today = now_ist.strftime("%Y-%m-%d")
    day_bars = completed_bars([b for b in bars if b["date"] == today], now_ist)
    rng = opening_range(day_bars)
    if rng is None:
        if now_ist.strftime("%H:%M") < RANGE_END:
            return {"status": "WAITING", "reason": "Opening range (09:15-09:30 IST) is still forming."}
        return {"status": "NO_DATA",
                "reason": "The feed is missing opening-range bars for today (it may be delayed); no signal."}
    or_high, or_low = rng

    hit = first_breakout(day_bars, direction)
    if hit:
        i, side = hit
        bar = day_bars[i]
        level = or_high if side == "long" else or_low
        word = "above range high" if side == "long" else "below range low"
        return {
            "status": "TRIGGERED",
            "setup": "ORB Breakout" if side == "long" else "ORB Breakdown",
            "side": side,
            "bar_time": bar["time"],
            "trigger_price": bar["close"],
            "or_high": or_high,
            "or_low": or_low,
            "reason": f"Bar at {bar['time']} closed @ ₹{bar['close']:,.2f} {word} ₹{level:,.2f}"
        }

    last_close = day_bars[-1]["close"]
    inside = or_low <= last_close <= or_high
    return {
        "status": "WAITING",
        "or_high": or_high,
        "or_low": or_low,
        "last_price": last_close,
        "reason": (f"Trading inside range ({or_low:,.2f} - {or_high:,.2f}). Current: ₹{last_close:,.2f}"
                   if inside else
                   f"No {direction} signal: the range ({or_low:,.2f} - {or_high:,.2f}) broke the other "
                   f"way or the entry window has passed. Current: ₹{last_close:,.2f}")
    }


def main():
    parser = argparse.ArgumentParser(description="Indian Market Intraday Entry Watcher")
    parser.add_argument("symbol", default="^NSEI", nargs="?", help="Symbol to check (default: ^NSEI)")
    parser.add_argument("--direction", choices=("long", "short", "both"), default="both",
                        help="Which breaks to signal (default: both)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    res = evaluate_orb_entry(args.symbol, args.direction)
    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("=" * 60)
    print(f"⏱️ INDIAN MARKET ENTRY MONITOR: {args.symbol}")
    print("=" * 60)
    print(f"Status: {res['status']}")
    print(f"Reason: {res['reason']}")
    if "or_high" in res:
        print(f"15m Opening Range: ₹{res['or_low']:,.2f} - ₹{res['or_high']:,.2f}")
    print("Yahoo's NSE feed can lag the exchange; confirm the level in Kite before acting.")


if __name__ == "__main__":
    main()
