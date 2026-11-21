#!/usr/bin/env python3
"""Opening-range breakout backtest for the Indian market. Standard library only.

Replays the exact rule trader-entry/entry_indian.py signals, on real 5-minute
bars, and reports the result AFTER costs:

  - Range: 09:15-09:30 IST. Signal: first completed bar closing outside it.
  - Entry: the NEXT bar's open (you cannot trade the close you just saw).
  - Stop: range midpoint (default) or the far side of the range.
  - Target: a multiple of the risk. Flat at 15:15 IST if neither is hit.
  - If one bar touches both the stop and the target, the stop is assumed first.
  - A gap through the stop is filled at the gap price, not at the stop.
  - Costs: slippage on each side plus round-trip charges, as a percent of price.

Data: Yahoo gives about 60 trading days of 5-minute bars for free. For one to
two years use --source kite (needs your Kite login) or --source csv.

It measures the move in the underlying (close to an index future or a stock
held intraday). A bought option also loses time value and pays a wider spread,
so an option buyer's result is WORSE than what this prints. Not financial advice.
"""

import argparse
import csv
import datetime
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "trader-entry"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from entry_indian import fetch_5m_bars, first_breakout, opening_range

KITE_TOKENS = {"^NSEI": 256265, "NIFTY": 256265, "^NSEBANK": 260105, "BANKNIFTY": 260105,
               "^BSESN": 265, "SENSEX": 265}
MIN_TRADES = 30


def load_csv(path):
    """CSV with columns datetime (IST, 'YYYY-MM-DD HH:MM'), open, high, low, close[, volume]."""
    bars = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().lower(): v for k, v in row.items()}
            stamp = (row.get("datetime") or row.get("date") or "").strip().replace("T", " ")[:16]
            dt = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M")
            bars.append({"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
                         "open": float(row["open"]), "high": float(row["high"]),
                         "low": float(row["low"]), "close": float(row["close"]),
                         "volume": float(row.get("volume") or 0)})
    bars.sort(key=lambda b: (b["date"], b["time"]))
    return bars


def load_kite(symbol, days, token=None):
    """5-minute history from Kite Connect (read-only). Kite allows about 100 days per request."""
    sys.path.insert(0, os.path.join(ROOT, "trader-broker"))
    from kite import _load_kite
    token = token or KITE_TOKENS.get(symbol.upper())
    if not token:
        raise ValueError("pass --kite-token for %s (see Kite's instruments list)" % symbol)
    client = _load_kite(os.path.join(ROOT, "trader", "state", "kite_session.json"))
    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=days)
    bars = []
    while start < end:
        chunk_end = min(start + datetime.timedelta(days=90), end)
        for row in client.historical_data(token, start, chunk_end, "5minute"):
            dt = row["date"]
            bars.append({"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
                         "open": row["open"], "high": row["high"], "low": row["low"],
                         "close": row["close"], "volume": row.get("volume") or 0})
        start = chunk_end
    unique = {(b["date"], b["time"]): b for b in bars}
    return [unique[key] for key in sorted(unique)]


def sessions(bars):
    """Group bars into trading days, oldest first."""
    days = {}
    for bar in bars:
        days.setdefault(bar["date"], []).append(bar)
    return [days[d] for d in sorted(days)]


def simulate_day(day_bars, direction="both", stop_mode="mid", rr=1.5, last_entry="11:30",
                 flat_by="15:15", min_range_pct=0.0, max_range_pct=100.0,
                 slippage_pct=0.01, cost_pct=0.05):
    """One session -> one trade dict, or None when the rule gives no trade that day."""
    rng = opening_range(day_bars)
    if rng is None:
        return None
    or_high, or_low = rng
    range_pct = (or_high - or_low) / or_low * 100.0
    if not (min_range_pct <= range_pct <= max_range_pct):
        return None
    hit = first_breakout(day_bars, direction, last_entry)
    if hit is None:
        return None
    i, side = hit
    if i + 1 >= len(day_bars) or day_bars[i + 1]["time"] >= flat_by:
        return None
    sign = 1 if side == "long" else -1
    entry_bar = day_bars[i + 1]
    entry = entry_bar["open"]
    if stop_mode == "range":
        stop = or_low if side == "long" else or_high
    else:
        stop = (or_high + or_low) / 2.0
    risk = (entry - stop) * sign
    if risk <= 0:
        return None  # opened beyond the stop: there is no trade to take
    target = entry + sign * rr * risk

    exit_price, reason, exit_time = None, None, None
    for bar in day_bars[i + 1:]:
        if bar["time"] >= flat_by:
            exit_price, reason, exit_time = bar["open"], "time", bar["time"]
            break
        adverse = bar["low"] if side == "long" else bar["high"]
        favourable = bar["high"] if side == "long" else bar["low"]
        if (adverse - stop) * sign <= 0:
            gap = bar["open"] if (bar["open"] - stop) * sign < 0 else stop
            exit_price, reason, exit_time = gap, "stop", bar["time"]
            break
        if (favourable - target) * sign >= 0:
            exit_price, reason, exit_time = target, "target", bar["time"]
            break
    if exit_price is None:
        last = day_bars[-1]
        exit_price, reason, exit_time = last["close"], "time", last["time"]

    gross = (exit_price - entry) * sign
    costs = entry * (2 * slippage_pct + cost_pct) / 100.0
    net = gross - costs
    return {"date": entry_bar["date"], "side": side, "entry_time": entry_bar["time"],
            "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
            "exit_time": exit_time, "exit": round(exit_price, 2), "reason": reason,
            "range_pct": round(range_pct, 3), "risk": round(risk, 2),
            "gross_pts": round(gross, 2), "costs_pts": round(costs, 2), "net_pts": round(net, 2),
            "gross_r": round(gross / risk, 3), "net_r": round(net / risk, 3)}


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def summarize(trades, days_tested):
    n = len(trades)
    out = {"days_tested": days_tested, "trades": n}
    if not n:
        out["verdict"] = "No trades: the rule never fired on this data."
        return out
    net = [t["net_r"] for t in trades]
    gross = [t["gross_r"] for t in trades]
    mean = _mean(net)
    sd = math.sqrt(sum((x - mean) ** 2 for x in net) / (n - 1)) if n > 1 else 0.0
    half_width = 1.96 * sd / math.sqrt(n) if n > 1 else float("inf")
    wins = [t["net_pts"] for t in trades if t["net_pts"] > 0]
    losses = [-t["net_pts"] for t in trades if t["net_pts"] <= 0]
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for x in net:
        equity += x
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    first, second = net[:n // 2], net[n // 2:]
    out.update({
        "first_date": trades[0]["date"], "last_date": trades[-1]["date"],
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "avg_gross_r": round(_mean(gross), 3),
        "avg_net_r": round(mean, 3),
        "net_r_95ci": [round(mean - half_width, 3), round(mean + half_width, 3)] if n > 1 else None,
        "total_net_r": round(sum(net), 2),
        "total_net_pts": round(sum(t["net_pts"] for t in trades), 2),
        "total_costs_pts": round(sum(t["costs_pts"] for t in trades), 2),
        "profit_factor": round(sum(wins) / sum(losses), 2) if sum(losses) > 0 else None,
        "max_drawdown_r": round(drawdown, 2),
        "first_half_avg_net_r": round(_mean(first), 3),
        "second_half_avg_net_r": round(_mean(second), 3),
        "exits": {r: sum(1 for t in trades if t["reason"] == r) for r in ("target", "stop", "time")},
        "by_side": {s: {"trades": len(rows), "avg_net_r": round(_mean(rows), 3)}
                    for s in ("long", "short")
                    for rows in [[t["net_r"] for t in trades if t["side"] == s]] if rows},
    })
    if n < MIN_TRADES:
        out["verdict"] = ("Too few trades to judge (%d, need at least %d). Test more history "
                          "before believing any number here." % (n, MIN_TRADES))
    elif mean <= 0:
        out["verdict"] = ("No edge after costs on this data (average %+.3fR per trade). "
                          "Do not trade this rule as it stands." % mean)
    elif mean - half_width <= 0 or _mean(first) <= 0 or _mean(second) <= 0:
        out["verdict"] = ("Not proven: the average is positive but it could be luck (the range of "
                          "likely values includes zero, or one half of the period lost money).")
    else:
        out["verdict"] = ("Positive after costs in both halves of this sample. That is a reason to "
                          "test more history and paper trade, not proof of future profit.")
    return out


def run(bars, **params):
    days = sessions(bars)
    trades = [t for t in (simulate_day(day, **params) for day in days) if t]
    return trades, summarize(trades, len(days))


def print_report(symbol, source, params, stats):
    print("=" * 66)
    print("📊 OPENING-RANGE BREAKOUT BACKTEST (after costs)")
    print("=" * 66)
    print(f"Symbol: {symbol} | Data: {source} | Sessions tested: {stats['days_tested']}")
    print(f"Rule:   {params['direction']} breaks until {params['last_entry']}, stop at "
          f"{'range midpoint' if params['stop_mode'] == 'mid' else 'far side of range'}, "
          f"target {params['rr']}R, flat by {params['flat_by']}")
    print(f"Costs:  {params['slippage_pct']}% slippage per side + {params['cost_pct']}% charges per round trip")
    if not stats["trades"]:
        print(f"\nVerdict: {stats['verdict']}")
        return
    print(f"\nTrades: {stats['trades']} ({stats['first_date']} to {stats['last_date']})")
    print(f"  Win rate:              {stats['win_rate_pct']}%")
    print(f"  Average per trade:     {stats['avg_gross_r']:+.3f}R before costs, {stats['avg_net_r']:+.3f}R after")
    if stats["net_r_95ci"]:
        print(f"  Likely range (95%):    {stats['net_r_95ci'][0]:+.3f}R to {stats['net_r_95ci'][1]:+.3f}R per trade")
    print(f"  Total:                 {stats['total_net_r']:+.2f}R, {stats['total_net_pts']:+,.2f} points "
          f"(costs took {stats['total_costs_pts']:,.2f} points)")
    pf = stats["profit_factor"]
    print(f"  Profit factor:         {pf if pf is not None else 'n/a (no losing trades)'}")
    print(f"  Worst drawdown:        {stats['max_drawdown_r']}R")
    print(f"  First half / second:   {stats['first_half_avg_net_r']:+.3f}R / {stats['second_half_avg_net_r']:+.3f}R")
    ex = stats["exits"]
    print(f"  Exits:                 target {ex['target']}, stop {ex['stop']}, 15:15 or close {ex['time']}")
    for side, row in stats["by_side"].items():
        print(f"  {side.capitalize():5} trades:          {row['trades']} at {row['avg_net_r']:+.3f}R")
    print(f"\nVerdict: {stats['verdict']}")
    print("This is the underlying's move. A bought option also pays time decay and a wider spread.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Opening-range breakout backtest for NSE/BSE, after costs")
    p.add_argument("--symbol", default="^NSEI", help="Yahoo symbol (^NSEI, ^NSEBANK, RELIANCE.NS ...)")
    p.add_argument("--source", choices=("yahoo", "kite", "csv"), default="yahoo")
    p.add_argument("--csv", help="CSV of 5-minute bars for --source csv")
    p.add_argument("--days", type=int, default=365, help="Calendar days of history for --source kite")
    p.add_argument("--kite-token", type=int, help="Kite instrument token for --source kite")
    p.add_argument("--direction", choices=("long", "short", "both"), default="both")
    p.add_argument("--stop", dest="stop_mode", choices=("mid", "range"), default="mid",
                   help="mid = range midpoint, range = far side of the range")
    p.add_argument("--rr", type=float, default=1.5, help="Target as a multiple of the risk")
    p.add_argument("--last-entry", default="11:30", help="No new signals after this IST time")
    p.add_argument("--flat-by", default="15:15", help="Exit time if neither stop nor target is hit")
    p.add_argument("--min-range-pct", type=float, default=0.0, help="Skip days with a smaller opening range")
    p.add_argument("--max-range-pct", type=float, default=100.0, help="Skip days with a larger opening range")
    p.add_argument("--slippage-pct", type=float, default=0.01, help="Slippage per side, percent of price")
    p.add_argument("--cost-pct", type=float, default=0.05,
                   help="Brokerage, STT, exchange fees, GST and stamp duty per round trip, percent of "
                        "price. Take the real figure from your broker's contract note.")
    p.add_argument("--trades-csv", help="Write every trade to this CSV file")
    p.add_argument("--json", action="store_true", help="Output the summary as JSON")
    args = p.parse_args(argv)
    if args.rr <= 0:
        p.error("--rr must be above zero")

    try:
        if args.source == "csv":
            if not args.csv:
                p.error("--source csv needs --csv FILE")
            bars = load_csv(args.csv)
        elif args.source == "kite":
            bars = load_kite(args.symbol, args.days, args.kite_token)
        else:
            bars = fetch_5m_bars(args.symbol, "60d")
    except Exception as exc:
        print("backtest_indian.py: could not load bars: %s" % exc, file=sys.stderr)
        return 1

    params = {k: getattr(args, k) for k in ("direction", "stop_mode", "rr", "last_entry", "flat_by",
                                            "min_range_pct", "max_range_pct", "slippage_pct", "cost_pct")}
    trades, stats = run(bars, **params)
    if args.trades_csv and trades:
        with open(args.trades_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(trades)
    if args.json:
        print(json.dumps({"symbol": args.symbol, "source": args.source, "params": params,
                          "summary": stats}, indent=2))
    else:
        print_report(args.symbol, args.source, params, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
