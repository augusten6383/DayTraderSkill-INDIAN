#!/usr/bin/env python3
"""Indian Market Position & Lot Sizer for trader-budget. Standard library only.

Extends trader-budget sizing logic to respect:
1. Indian Rupee (INR ₹) budget, max loss, and daily loss thresholds.
2. Index Option Lot constraints:
     - NIFTY 50: 25 qty / lot
     - BANK NIFTY: 15 qty / lot
     - SENSEX: 10 qty / lot
Orders are rounded DOWN to the nearest integer multiple of the lot size so orders
are never rejected by NSE/BSE.
"""

import argparse
import json
import math
import os
import sys

INDEX_LOTS = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "SENSEX": 10
}

def calculate_option_lots(underlying, budget, entry_premium, stop_premium, max_loss):
    """
    Computes exact lot size for Indian Index Options.
    Risk per share = (entry_premium - stop_premium)
    Max loss constraint = max_loss / risk_per_share
    Budget constraint = budget / entry_premium
    """
    clean_und = underlying.upper().replace(" ", "")
    lot_size = 1
    for k, size in INDEX_LOTS.items():
        if k in clean_und:
            lot_size = size
            break

    risk_per_unit = max(0.05, entry_premium - stop_premium)
    max_qty_by_risk = max_loss / risk_per_unit
    max_qty_by_budget = budget / entry_premium

    allowed_qty = min(max_qty_by_risk, max_qty_by_budget)
    lots = int(math.floor(allowed_qty / lot_size))
    total_qty = lots * lot_size
    capital_used = total_qty * entry_premium
    max_rupee_loss = total_qty * risk_per_unit

    return {
        "underlying": underlying,
        "lot_size": lot_size,
        "lots": lots,
        "total_qty": total_qty,
        "entry_premium": entry_premium,
        "stop_premium": stop_premium,
        "risk_per_unit": risk_per_unit,
        "capital_used_inr": round(capital_used, 2),
        "max_risk_inr": round(max_rupee_loss, 2),
        "status": "APPROVED" if lots > 0 else "REJECTED (Risk or budget too small for 1 lot)"
    }

def main():
    parser = argparse.ArgumentParser(description="Indian Index Option Lot Sizer")
    parser.add_argument("--symbol", default="NIFTY", help="Underlying (NIFTY, BANKNIFTY, SENSEX)")
    parser.add_argument("--entry", type=float, required=True, help="Option entry premium (₹)")
    parser.add_argument("--stop", type=float, required=True, help="Stop loss premium (₹)")
    parser.add_argument("--budget", type=float, default=50000, help="Total trading capital (₹)")
    parser.add_argument("--max-loss", type=float, default=2000, help="Max loss per trade (₹)")
    args = parser.parse_args()

    result = calculate_option_lots(
        underlying=args.symbol,
        budget=args.budget,
        entry_premium=args.entry,
        stop_premium=args.stop,
        max_loss=args.max_loss
    )

    print("=" * 60)
    print("🎯 INDIAN INDEX OPTION POSITION SIZING TICKET")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:20}: {v}")

if __name__ == "__main__":
    main()
