#!/usr/bin/env python3
"""Automated Indian Market Telegram Signal & Alert Dispatcher.
Standard library only (urllib + json).

Sends structured, beautifully formatted Telegram notifications:
  - 🔔 Morning Market Bell & FII/DII Sentiment (09:15 IST)
  - 🚨 15-Minute Opening Range Breakout (ORB) Signals (09:30 - 15:00 IST)
  - ⏰ Intraday Auto Square-Off Reminder (15:10 IST)
"""

import json
import os
import sys
import urllib.parse
import urllib.request

def load_telegram_config():
    """Loads bot token and chat ID from environment variables or settings.json"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        settings_path = os.path.join(os.path.dirname(__file__), "..", "settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                data = json.load(f)
                token = token or data.get("telegram_bot_token")
                chat_id = chat_id or data.get("telegram_chat_id")

    return token, chat_id

def send_telegram_message(text, parse_mode="HTML"):
    """Dispatches message to Telegram via Telegram Bot HTTP API"""
    token, chat_id = load_telegram_config()
    if not token or not chat_id:
        print("⚠️ Warning: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Skipping dispatch.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("ok", False)
    except Exception as e:
        sys.stderr.write(f"Failed to send Telegram message: {e}\n")
        return False

def send_morning_bell_alert(nifty_spot, banknifty_spot, sensex_spot, fii_summary=""):
    """Dispatches 09:15 IST Morning Market Bell"""
    msg = (
        "🔔 <b>INDIAN MARKET OPEN (09:15 IST)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>NIFTY 50:</b> ₹{nifty_spot:,.2f}\n"
        f"📈 <b>BANK NIFTY:</b> ₹{banknifty_spot:,.2f}\n"
        f"📈 <b>SENSEX:</b> ₹{sensex_spot:,.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>FII/DII Note:</b> {fii_summary if fii_summary else 'Normal market open. 15m ORB monitor active.'}\n\n"
        "<i>⚡ Opening Range (09:15 - 09:30 IST) is now forming...</i>"
    )
    return send_telegram_message(msg)

def send_orb_signal(index_name, spot_price, range_high, range_low, strike_opt, premium_est, stop_loss, target, lots, qty):
    """Dispatches Opening Range Breakout (ORB) Trade Signal"""
    risk = round(premium_est - stop_loss, 2)
    reward = round(target - premium_est, 2)
    rr = round(reward / risk, 1) if risk > 0 else 1.5

    msg = (
        f"🚨 <b>INTRADAY TRADE SIGNAL: {index_name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Setup:</b> 15-Minute Opening Range Breakout (ORB)\n"
        f"📊 <b>Spot Breakout:</b> ₹{spot_price:,.2f} (Cleared Range: {range_low:,.0f} - {range_high:,.0f})\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Recommended Contract:</b> <code>{strike_opt}</code>\n"
        f"💰 <b>Est. Entry Premium:</b> ₹{premium_est:,.2f}\n"
        f"🛑 <b>Stop Loss:</b> ₹{stop_loss:,.2f} (Risk: ₹{risk})\n"
        f"🎯 <b>Target:</b> ₹{target:,.2f} (Reward: ₹{reward} | {rr}:1 R:R)\n"
        f"📦 <b>Suggested Size:</b> {lots} Lot(s) ({qty} Qty)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ <b>Rule:</b> Enforce 15:15 IST auto-square-off if open.\n"
        "<i>⚠️ Trade with disciplined risk management.</i>"
    )
    return send_telegram_message(msg)

def send_squareoff_reminder():
    """Dispatches 15:10 IST Auto Square-Off Reminder"""
    msg = (
        "⏰ <b>INTRADAY SQUARE-OFF REMINDER (15:10 IST)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Market closes in 20 minutes (15:30 IST).\n"
        "Please ensure all intraday MIS/Option positions are closed to avoid auto-square-off penalty charges from the broker."
    )
    return send_telegram_message(msg)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Testing Telegram message delivery...")
        ok = send_telegram_message("👋 <b>Day Trader Skill Bot Connected!</b>\nYour Indian Index Options Telegram alerts are active.")
        if ok:
            print("✅ Test message delivered to your Telegram!")
        else:
            print("❌ Delivery failed. Ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.")
    else:
        print("Telegram notifier module loaded.")
