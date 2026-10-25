#!/usr/bin/env python3
"""Indian Market Exit & Trade Plan Generator for trader-exit. Standard library only.

Plans stop-loss, take-profit, and intraday flat-by time for Indian trades:
  - Default Stop: Opening Range Midpoint or ATR-based.
  - Default Target: 1R or 2R (Reward-to-Risk).
  - Square-off time: 15:15 IST (Enforced before market close at 15:30 IST).
"""

import argparse
import datetime
import json
import os
import sys

def plan_exit(symbol, entry, or_high=None, or_low=None, risk_reward=1.5):
    if or_high and or_low:
        midpoint = (or_high + or_low) / 2.0
        stop = round(midpoint, 2)
    else:
        # Default 0.5% stop if range not specified
        stop = round(entry * 0.995, 2)

    risk_per_share = round(entry - stop, 2)
    target = round(entry + (risk_per_share * risk_reward), 2)

    plan = {
        "symbol": symbol,
        "entry": entry,
        "stop_loss": stop,
        "target": target,
        "risk_per_share": risk_per_share,
        "reward_per_share": round(target - entry, 2),
        "reward_to_risk": f"{risk_reward}:1",
        "flat_by_time": "15:15 IST",
        "market_close": "15:30 IST"
    }
    return plan

def main():
    parser = argparse.ArgumentParser(description="Indian Market Exit & Target Planner")
    parser.add_argument("--symbol", default="NIFTY", help="Symbol")
    parser.add_argument("--entry", type=float, required=True, help="Entry price (₹)")
    parser.add_argument("--or-high", type=float, help="Opening range high (₹)")
    parser.add_argument("--or-low", type=float, help="Opening range low (₹)")
    parser.add_argument("--rr", type=float, default=1.5, help="Reward-to-risk ratio (default 1.5)")
    args = parser.parse_args()

    plan = plan_exit(args.symbol, args.entry, args.or_high, args.or_low, args.rr)

    print("=" * 60)
    print("🎯 INDIAN MARKET TRADE EXIT & BRACKET PLAN")
    print("=" * 60)
    print(f"Symbol:           {plan['symbol']}")
    print(f"Entry Price:      ₹{plan['entry']:,.2f}")
    print(f"Stop Loss:        ₹{plan['stop_loss']:,.2f} (Risk: ₹{plan['risk_per_share']:,.2f})")
    print(f"Take Profit:      ₹{plan['target']:,.2f} (Reward: ₹{plan['reward_per_share']:,.2f})")
    print(f"Reward : Risk:    {plan['reward_to_risk']}")
    print(f"Intraday Flat By: {plan['flat_by_time']} (Market close: {plan['market_close']})")

if __name__ == "__main__":
    main()
