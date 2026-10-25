#!/usr/bin/env python3
"""Indian Universe Builder for trader-scanner. Standard library only.

Builds trader/universe.txt containing:
1. Core Indian Indices: NIFTY 50, NIFTY BANK, BSE SENSEX
2. Top liquid NIFTY 50 / F&O stock constituents (Reliance, HDFC Bank, ICICI Bank, TCS, Infosys, etc.)
Outputs in the exact format expected by trader-scanner: SYMBOL|Company Name
"""

import os
import sys

# High liquidity Nifty 50 constituents for day trading & stock options
INDIAN_STOCKS = [
    # Top Index Heavyweights
    ("RELIANCE.NS", "Reliance Industries Ltd"),
    ("HDFCBANK.NS", "HDFC Bank Ltd"),
    ("ICICIBANK.NS", "ICICI Bank Ltd"),
    ("INFY.NS", "Infosys Ltd"),
    ("TCS.NS", "Tata Consultancy Services Ltd"),
    ("ITC.NS", "ITC Ltd"),
    ("LT.NS", "Larsen & Toubro Ltd"),
    ("SBIN.NS", "State Bank of India"),
    ("BHARTIARTL.NS", "Bharti Airtel Ltd"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank Ltd"),
    ("AXISBANK.NS", "Axis Bank Ltd"),
    ("HINDUNILVR.NS", "Hindustan Unilever Ltd"),
    ("BAJFINANCE.NS", "Bajaj Finance Ltd"),
    ("MARUTI.NS", "Maruti Suzuki India Ltd"),
    ("TATAMOTORS.NS", "Tata Motors Ltd"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical Industries Ltd"),
    ("TITAN.NS", "Titan Company Ltd"),
    ("NTPC.NS", "NTPC Ltd"),
    ("POWERGRID.NS", "Power Grid Corporation of India Ltd"),
    ("TATASTEEL.NS", "Tata Steel Ltd"),
    ("ASIANPAINT.NS", "Asian Paints Ltd"),
    ("M&M.NS", "Mahindra & Mahindra Ltd"),
    ("ADANIENT.NS", "Adani Enterprises Ltd"),
    ("ADANIPORTS.NS", "Adani Ports and SEZ Ltd"),
    ("COALINDIA.NS", "Coal India Ltd"),
    ("BAJAJFINSV.NS", "Bajaj Finserv Ltd"),
    ("ONGC.NS", "Oil & Natural Gas Corporation Ltd"),
    ("JSWSTEEL.NS", "JSW Steel Ltd"),
    ("WIPRO.NS", "Wipro Ltd"),
    ("HCLTECH.NS", "HCL Technologies Ltd")
]

def build_universe(out_path="trader/universe.txt"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sym, name in INDIAN_STOCKS:
            f.write(f"{sym}|{name}\n")
    print(f"✅ Generated Indian trading universe with {len(INDIAN_STOCKS)} liquid F&O stocks at: {out_path}")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "trader/universe.txt"
    build_universe(out)
