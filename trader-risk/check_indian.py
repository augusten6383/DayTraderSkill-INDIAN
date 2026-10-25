#!/usr/bin/env python3
"""Indian Market Risk & Gatekeeper Check for trader-risk. Standard library only.

Checks orders against Indian regulatory and account risk limits:
  1. Market Status: Is NSE/BSE open (09:15 - 15:30 IST) on a non-holiday?
  2. Max Loss: Position loss does not exceed max_loss_per_trade_inr (e.g. ₹2,000).
  3. Daily Loss: Accumulated loss does not exceed max_daily_loss_inr (e.g. ₹5,000).
  4. Max Trades: Does not exceed max_trades_per_day (default 3).
  5. Square-Off Rule: Blocks new intraday entries after 15:00 IST.
  6. Lot Multiples: Ensures quantity is an exact multiple of the index lot.
"""

import argparse
import datetime
import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from market_calendar_indian import to_ist, is_market_open, SQUARE_OFF_TIME

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config_indian.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "max_loss_per_trade_inr": 2000,
        "max_daily_loss_inr": 5000,
        "max_trades_per_day": 3,
        "indices": {"NIFTY": {"lot_size": 25}, "BANKNIFTY": {"lot_size": 15}, "SENSEX": {"lot_size": 10}}
    }

def check_order_risk(symbol, qty, entry, stop, realized_loss_today=0, trades_today=0):
    cfg = load_config()
    reasons = []
    passed = True

    now_ist = to_ist()
    mkt_open, mkt_msg = is_market_open(now_ist)
    if not mkt_open:
        reasons.append(f"MARKET_CLOSED: {mkt_msg}")
        passed = False

    # Check 15:00 cutoff for new intraday entries
    if now_ist.time() >= datetime.time(15, 0):
        reasons.append(f"TIME_LIMIT: Entries blocked after 15:00 IST (Current: {now_ist.strftime('%H:%M')})")
        passed = False

    # Check Max Trades per Day
    max_trades = cfg.get("max_trades_per_day", 3)
    if trades_today >= max_trades:
        reasons.append(f"TRADES_LIMIT: Reached daily limit of {max_trades} trades")
        passed = False

    # Check Daily Loss
    max_daily_loss = cfg.get("max_daily_loss_inr", 5000)
    if realized_loss_today >= max_daily_loss:
        reasons.append(f"DAILY_LOSS_LIMIT: Realized ₹{realized_loss_today} loss reaches ₹{max_daily_loss} cap")
        passed = False

    # Check Trade Risk
    risk_per_share = abs(entry - stop)
    total_trade_risk = qty * risk_per_share
    max_trade_loss = cfg.get("max_loss_per_trade_inr", 2000)
    if total_trade_risk > max_trade_loss:
        reasons.append(f"TRADE_LOSS_LIMIT: Potential loss ₹{total_trade_risk:.2f} exceeds cap of ₹{max_trade_loss}")
        passed = False

    # Check Lot multiples for Indices
    for idx, details in cfg.get("indices", {}).items():
        if idx in symbol.upper():
            lot = details.get("lot_size", 1)
            if qty % lot != 0:
                reasons.append(f"LOT_SIZE_ERROR: Qty {qty} is not a multiple of {idx} lot size ({lot})")
                passed = False
            break

    return {
        "status": "PASS" if passed else "BLOCK",
        "symbol": symbol,
        "qty": qty,
        "potential_loss_inr": round(total_trade_risk, 2),
        "reasons": reasons if reasons else ["All risk parameters passed successfully."]
    }

def main():
    parser = argparse.ArgumentParser(description="Indian Market Risk Gatekeeper")
    parser.add_argument("--symbol", default="NIFTY", help="Trading Symbol")
    parser.add_argument("--qty", type=int, required=True, help="Order quantity")
    parser.add_argument("--entry", type=float, required=True, help="Entry price (₹)")
    parser.add_argument("--stop", type=float, required=True, help="Stop loss price (₹)")
    parser.add_argument("--realized-loss", type=float, default=0, help="Loss already realized today (₹)")
    parser.add_argument("--trades", type=int, default=0, help="Number of trades executed today")
    args = parser.parse_args()

    res = check_order_risk(
        symbol=args.symbol,
        qty=args.qty,
        entry=args.entry,
        stop=args.stop,
        realized_loss_today=args.realized_loss,
        trades_today=args.trades
    )

    print("=" * 60)
    print("🛡️ INDIAN TRADING RISK GATEKEEPER CHECK")
    print("=" * 60)
    badge = "🟢 PASS" if res["status"] == "PASS" else "🔴 BLOCK"
    print(f"Result:             {badge}")
    print(f"Symbol:             {res['symbol']}")
    print(f"Qty:                {res['qty']}")
    print(f"Max Trade Risk:     ₹{res['potential_loss_inr']:,.2f}")
    print("\nReasons / Checks:")
    for r in res["reasons"]:
        print(f"  • {r}")

if __name__ == "__main__":
    main()
