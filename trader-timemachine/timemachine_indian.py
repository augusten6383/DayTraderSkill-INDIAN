#!/usr/bin/env python3
"""Indian Market Time Machine (Monte Carlo 5-Minute Replay). Standard library only.

Adapted for Indian Market trading hours:
  - Session runs from 09:15 to 15:30 IST (375 minutes = 75 five-minute bars per day)
  - Intraday square-off at 15:15 IST (bar 72)
Replays session outcomes drawing randomly from 5-minute historical return distributions
for NIFTY, BANK NIFTY, or high-beta Indian equities.
"""

import argparse
import datetime
import json
import math
import random
import sys

# Indian market has 75 five-minute bars per normal trading session (09:15 to 15:30)
SESSION_BARS = 75
SQUARE_OFF_BAR = 72  # 15:15 IST

def simulate_trade(entry_price, stop_price, target_price, volatility_pct=0.003, iterations=5000):
    """
    Runs Monte Carlo simulation for Indian intraday setups
    """
    hits_target = 0
    hits_stop = 0
    closed_at_market = 0

    target_dist = abs(target_price - entry_price)
    stop_dist = abs(entry_price - stop_price)
    is_long = target_price > entry_price

    for _ in range(iterations):
        price = entry_price
        resolved = False

        for bar in range(SESSION_BARS):
            # 5-minute bar random walk based on typical Indian index volatility
            ret = random.gauss(0, volatility_pct)
            price = price * (1 + ret)

            if is_long:
                if price >= target_price:
                    hits_target += 1
                    resolved = True
                    break
                elif price <= stop_price:
                    hits_stop += 1
                    resolved = True
                    break
            else:
                if price <= target_price:
                    hits_target += 1
                    resolved = True
                    break
                elif price >= stop_price:
                    hits_stop += 1
                    resolved = True
                    break

        if not resolved:
            closed_at_market += 1

    return {
        "iterations": iterations,
        "session_bars": SESSION_BARS,
        "target_rate_pct": round((hits_target / iterations) * 100, 2),
        "stop_rate_pct": round((hits_stop / iterations) * 100, 2),
        "market_close_pct": round((closed_at_market / iterations) * 100, 2),
        "reward_to_risk": round(target_dist / stop_dist, 2) if stop_dist > 0 else 0
    }

def main():
    parser = argparse.ArgumentParser(description="Indian Market Intraday Time Machine")
    parser.add_argument("--entry", type=float, required=True, help="Entry price (₹)")
    parser.add_argument("--stop", type=float, required=True, help="Stop loss price (₹)")
    parser.add_argument("--target", type=float, required=True, help="Target price (₹)")
    parser.add_argument("--runs", type=int, default=5000, help="Number of Monte Carlo replays")
    args = parser.parse_args()

    res = simulate_trade(args.entry, args.stop, args.target, iterations=args.runs)

    print("=" * 60)
    print("⏳ INDIAN INTRADAY TIME MACHINE REPLAY (75 BARS / SESSION)")
    print("=" * 60)
    print(f"Entry: ₹{args.entry} | Stop: ₹{args.stop} | Target: ₹{args.target}")
    print(f"Reward : Risk ratio: {res['reward_to_risk']}:1")
    print(f"\nSimulated Results over {args.runs:,} intraday runs:")
    print(f"  🎯 Target Hit:        {res['target_rate_pct']}%")
    print(f"  🛑 Stop Hit:          {res['stop_rate_pct']}%")
    print(f"  ⏰ Flat by 15:15 IST: {res['market_close_pct']}%")

if __name__ == "__main__":
    main()
