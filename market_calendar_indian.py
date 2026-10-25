#!/usr/bin/env python3
"""Indian Stock Market Calendar, Clock & Timezone Utilities for NSE / BSE.
Standard library only.

Provides official market timing for:
  - Timezone: Asia/Kolkata (IST = UTC+05:30)
  - Trading Hours: 09:15 to 15:30 IST
  - Pre-Open Session: 09:00 to 09:08 IST
  - Intraday Auto Square-Off: 15:15 IST
  - Exchange Holidays: Official NSE/BSE holidays (2026/2027)
"""

import datetime

# IST offset from UTC: exactly +5 hours 30 minutes (no Daylight Saving Time in India)
IST_OFFSET_MINUTES = 330
OPEN_TIME = datetime.time(9, 15)
CLOSE_TIME = datetime.time(15, 30)
SQUARE_OFF_TIME = datetime.time(15, 15)

# NSE / BSE Official Trading Holidays for 2026
NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id",
    "2026-08-15": "Independence Day",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-09": "Diwali Laxmi Pujan (Muhurat Trading evening)",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Gurunanak Jayanti",
    "2026-12-25": "Christmas"
}

def to_ist(utc_dt=None):
    """Converts UTC datetime to Indian Standard Time (IST)"""
    if utc_dt is None:
        utc_dt = datetime.datetime.utcnow()
    naive = utc_dt.replace(tzinfo=None) if hasattr(utc_dt, "replace") else utc_dt
    return naive + datetime.timedelta(minutes=IST_OFFSET_MINUTES)

def is_market_open(ist_dt=None):
    """Checks if NSE/BSE is currently open for normal trading"""
    if ist_dt is None:
        ist_dt = to_ist()
    
    # Check weekend (5 = Saturday, 6 = Sunday)
    if ist_dt.weekday() >= 5:
        return False, "Market is closed: Weekend"

    # Check holiday
    day_str = ist_dt.strftime("%Y-%m-%d")
    if day_str in NSE_HOLIDAYS_2026:
        return False, f"Market is closed: {NSE_HOLIDAYS_2026[day_str]}"

    curr_time = ist_dt.time()
    if curr_time < OPEN_TIME:
        return False, f"Pre-market: NSE/BSE opens at 09:15 IST (Current: {curr_time.strftime('%H:%M')})"
    if curr_time >= CLOSE_TIME:
        return False, f"Post-market: NSE/BSE closed at 15:30 IST (Current: {curr_time.strftime('%H:%M')})"

    return True, "NSE/BSE is OPEN"

def next_market_open(ist_dt=None):
    """Computes the next trading session open timestamp"""
    if ist_dt is None:
        ist_dt = to_ist()
    
    curr = ist_dt
    # If before 09:15 today and today is a trading day
    if curr.time() < OPEN_TIME and curr.weekday() < 5 and curr.strftime("%Y-%m-%d") not in NSE_HOLIDAYS_2026:
        return datetime.datetime.combine(curr.date(), OPEN_TIME)

    # Move to tomorrow
    curr = datetime.datetime.combine(curr.date() + datetime.timedelta(days=1), OPEN_TIME)
    while curr.weekday() >= 5 or curr.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026:
        curr += datetime.timedelta(days=1)
    return curr

if __name__ == "__main__":
    now_ist = to_ist()
    open_status, msg = is_market_open(now_ist)
    print(f"Current IST: {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Status:      {msg}")
    print(f"Next Open:   {next_market_open(now_ist).strftime('%Y-%m-%d %H:%M')} IST")
