# -*- coding: utf-8 -*-
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


import json
import pyotp
try:
    from SmartApi import SmartConnect
except ImportError:
    print("Error: smartapi-python is not installed. Run: pip install smartapi-python pyotp")
    exit(1)

# Load credentials from settings.json
with open("settings.json", "r") as f:
    config = json.load(f)

api_key = config.get("api_key")
client_id = config.get("client_id")
pin = config.get("pin")
totp_secret = config.get("totp_secret")

print(f"Connecting to Angel One SmartAPI with Client ID: {client_id}...")

smart_api = SmartConnect(api_key=api_key)

# Generate TOTP
totp_code = pyotp.TOTP(totp_secret).now()
print(f"Generated dynamic TOTP: {totp_code}")

# Authenticate
session = smart_api.generateSession(client_id, pin, totp_code)

if not session or not session.get("status"):
    print(f"\n❌ Login Failed: {session.get('message') if session else 'Unknown error'}")
    print("Full response:", session)
    exit(1)

print("\n✅ Login Successful!")
jwt_token = session["data"]["jwtToken"]
print("Session Token generated successfully.")

# Test fetching Spot quotes for NIFTY, BANK NIFTY, and SENSEX
indices_to_test = [
    {"name": "NIFTY 50", "exchange": "NSE", "symbol": "Nifty 50", "token": "99926000"},
    {"name": "BANK NIFTY", "exchange": "NSE", "symbol": "Nifty Bank", "token": "99926009"},
    {"name": "SENSEX", "exchange": "BSE", "symbol": "SENSEX", "token": "99919000"},
]

print("\n--- Live Index Quotes ---")
for idx in indices_to_test:
    try:
        quote = smart_api.ltpData(idx["exchange"], idx["symbol"], idx["token"])
        if quote and quote.get("status") and "data" in quote:
            ltp = quote["data"]["ltp"]
            print(f"📈 {idx['name']} ({idx['exchange']}): ₹{ltp:,.2f}")
        else:
            print(f"⚠️ {idx['name']}: Could not fetch LTP -> {quote.get('message')}")
    except Exception as e:
        print(f"⚠️ Error fetching {idx['name']}: {e}")

print("\nAngel One SmartAPI setup is ready to go!")
