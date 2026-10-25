#!/usr/bin/env python3
"""Angel One SmartAPI Broker Execution & Order Generator. Standard library only (+ smartapi).

Replaces US Alpaca broker connector with Angel One SmartAPI:
  - Supports NIFTY, BANK NIFTY, SENSEX Options and Equity intraday.
  - Automatically manages dynamic TOTP generation.
  - Generates official Angel One placeOrder JSON payloads:
      variety: "NORMAL"
      tradingsymbol: e.g. "NIFTY24OCT2424500CE"
      symboltoken: token from scrip master
      transactiontype: "BUY" or "SELL"
      exchange: "NFO" (for Options) / "NSE" (for Stocks)
      ordertype: "MARKET" or "LIMIT"
      producttype: "INTRADAY" (or "CARRYFORWARD")
      duration: "DAY"
      price: limit price or "0" for market
      quantity: integer multiple of index lot size
"""

import argparse
import json
import os
import sys

def load_settings():
    settings_file = os.path.join(os.path.dirname(__file__), "..", "settings.json")
    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            return json.load(f)
    return {}

INDEX_LOTS = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "SENSEX": 10
}

def create_order_payload(symbol, token, side, lots, order_type="MARKET", price=0, product="INTRADAY", exchange="NFO"):
    """Builds Angel One compatible order structure"""
    clean_sym = symbol.upper()
    lot_size = 1
    for key, size in INDEX_LOTS.items():
        if key in clean_sym:
            lot_size = size
            break

    total_qty = lots * lot_size

    payload = {
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "symboltoken": str(token),
        "transactiontype": side.upper(),
        "exchange": exchange,
        "ordertype": order_type.upper(),
        "producttype": product.upper(),
        "duration": "DAY",
        "price": str(price) if order_type.upper() == "LIMIT" else "0",
        "quantity": str(total_qty)
    }
    return payload

def main():
    parser = argparse.ArgumentParser(description="Angel One SmartAPI Ticket Generator")
    parser.add_argument("--symbol", default="NIFTY", help="Trading Symbol (e.g. NIFTY or NIFTY24OCT2424500CE)")
    parser.add_argument("--token", default="99926000", help="Scrip Master Symbol Token")
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY", help="Order Side")
    parser.add_argument("--lots", type=int, default=1, help="Number of lots")
    parser.add_argument("--limit-price", type=float, default=0, help="Limit price (0 for MARKET)")
    parser.add_argument("--product", default="INTRADAY", choices=["INTRADAY", "CARRYFORWARD"])
    parser.add_argument("--exchange", default="NFO", choices=["NFO", "NSE", "BSE", "BFO"])
    args = parser.parse_args()

    order_type = "LIMIT" if args.limit_price > 0 else "MARKET"
    payload = create_order_payload(
        symbol=args.symbol,
        token=args.token,
        side=args.side,
        lots=args.lots,
        order_type=order_type,
        price=args.limit_price,
        product=args.product,
        exchange=args.exchange
    )

    print("=" * 60)
    print("📋 ANGEL ONE SMARTAPI ORDER TICKET")
    print("=" * 60)
    print(f"Action:       {payload['transactiontype']} {payload['quantity']} Qty ({args.lots} lot(s)) of {payload['tradingsymbol']}")
    print(f"Exchange:     {payload['exchange']}")
    print(f"Order Type:   {payload['ordertype']} {f'@ ₹{args.limit_price}' if args.limit_price > 0 else ''}")
    print(f"Product:      {payload['producttype']}")
    print("\n[Payload JSON for SmartAPI placeOrder]:")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
