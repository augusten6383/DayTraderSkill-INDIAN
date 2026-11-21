#!/usr/bin/env python3
"""Indian Market Position & Lot Sizer for trader-budget. Standard library only.

Extends trader-budget sizing logic to respect:
1. Indian Rupee (INR ₹) budget, max loss, and daily loss thresholds.
2. Index Option Lot constraints, read from config_indian.json
   (refresh them with `python indian_instruments.py refresh`).
Orders are rounded DOWN to the nearest integer multiple of the lot size so orders
are never rejected by NSE/BSE.
"""

import argparse
import json
import math
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from indian_instruments import lot_size_for

def calculate_option_lots(underlying, budget, entry_premium, stop_premium, max_loss):
    """
    Computes exact lot size for Indian Index Options.
    Risk per share = (entry_premium - stop_premium)
    Max loss constraint = max_loss / risk_per_share
    Budget constraint = budget / entry_premium
    """
    lot_size = lot_size_for(underlying)

    problem = None
    if not (entry_premium > 0 and stop_premium > 0 and budget > 0 and max_loss > 0):
        problem = "entry, stop, budget and max loss must all be above zero"
    elif stop_premium >= entry_premium:
        problem = "the stop must be below the entry premium for a bought option"
    if problem:
        return {
            "underlying": underlying, "lot_size": lot_size, "lots": 0, "total_qty": 0,
            "entry_premium": entry_premium, "stop_premium": stop_premium,
            "risk_per_unit": 0, "capital_used_inr": 0, "max_risk_inr": 0,
            "status": "REJECTED (%s)" % problem,
        }

    risk_per_unit = round(entry_premium - stop_premium, 2)
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
