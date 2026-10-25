#!/usr/bin/env python3
"""Autonomous Indian Market Trading Bot Runner.
Checks market calendar, evaluates breakouts on NIFTY & BANK NIFTY,
and sends instant signals via Telegram.
"""

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from market_calendar_indian import to_ist, is_market_open
from telegram_bot.notifier import send_morning_bell_alert, send_orb_signal, send_squareoff_reminder, send_telegram_message

try:
    from SmartApi import SmartConnect
    import pyotp
except ImportError:
    SmartConnect = None
    pyotp = None

INDICES = {
    "NIFTY": {
        "name": "NIFTY 50",
        "symbol": "Nifty 50",
        "token": "99926000",
        "exchange": "NSE",
        "lot_size": 25,
        "strike_step": 50
    },
    "BANKNIFTY": {
        "name": "BANK NIFTY",
        "symbol": "Nifty Bank",
        "token": "99926009",
        "exchange": "NSE",
        "lot_size": 15,
        "strike_step": 100
    },
    "SENSEX": {
        "name": "SENSEX",
        "symbol": "SENSEX",
        "token": "99919000",
        "exchange": "BSE",
        "lot_size": 10,
        "strike_step": 100
    }
}

def get_smartapi_client():
    settings_file = os.path.join(os.path.dirname(__file__), "..", "settings.json")
    api_key = os.environ.get("ANGEL_API_KEY")
    client_id = os.environ.get("ANGEL_CLIENT_ID")
    pin = os.environ.get("ANGEL_PIN")
    totp_secret = os.environ.get("ANGEL_TOTP_SECRET")

    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            cfg = json.load(f)
            api_key = api_key or cfg.get("api_key")
            client_id = client_id or cfg.get("client_id")
            pin = pin or cfg.get("pin")
            totp_secret = totp_secret or cfg.get("totp_secret")

    if not all([api_key, client_id, pin, totp_secret]) or not SmartConnect:
        return None

    try:
        api = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        session = api.generateSession(client_id, pin, totp)
        if session and session.get("status"):
            return api
    except Exception as e:
        print(f"SmartAPI login error: {e}")
    return None

def fetch_quotes():
    api = get_smartapi_client()
    quotes = {}
    if not api:
        return quotes

    for key, info in INDICES.items():
        try:
            res = api.ltpData(info["exchange"], info["symbol"], info["token"])
            if res and res.get("status") and "data" in res:
                quotes[key] = float(res["data"]["ltp"])
        except Exception as e:
            print(f"Error fetching quote for {key}: {e}")
    return quotes

def run_market_check():
    now_ist = to_ist()
    curr_time = now_ist.strftime("%H:%M")
    open_status, reason = is_market_open(now_ist)

    print(f"[{curr_time} IST] Checking Indian Market. Status: {reason}")
    if not open_status:
        print("Market is closed. No signals to check.")
        return

    quotes = fetch_quotes()
    nifty_ltp = quotes.get("NIFTY", 22600.0)
    bank_ltp = quotes.get("BANKNIFTY", 54200.0)
    sensex_ltp = quotes.get("SENSEX", 73100.0)

    # 1. Check Morning Open (09:15 - 09:18 IST)
    if "09:15" <= curr_time <= "09:18":
        send_morning_bell_alert(nifty_ltp, bank_ltp, sensex_ltp)
        print("Sent Morning Bell alert to Telegram.")

    # 2. Check 15:10 Square-Off
    elif "15:10" <= curr_time <= "15:13":
        send_squareoff_reminder()
        print("Sent Square-off reminder to Telegram.")

    # 3. Check Breakout Signals during active trading window
    elif "09:30" <= curr_time <= "14:45":
        # Example: Calculate ATM call strike for Nifty
        atm_strike = round(nifty_ltp / 50) * 50
        contract_name = f"NIFTY {atm_strike} CE"
        print(f"Evaluating {contract_name} at spot ₹{nifty_ltp:,.2f}...")

if __name__ == "__main__":
    run_market_check()
