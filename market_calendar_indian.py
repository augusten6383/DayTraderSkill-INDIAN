#!/usr/bin/env python3
"""Indian Stock Market Calendar, Clock & Timezone Utilities for NSE / BSE.
Standard library only.

Provides official market timing for:
  - Timezone: Asia/Kolkata (IST = UTC+05:30)
  - Trading Hours: 09:15 to 15:30 IST
  - Intraday Auto Square-Off: 15:15 IST
  - Exchange Holidays: NSE capital-market trading holidays

The 2026 list below is NSE's own (holiday-master list, read 12-Nov-2026).
NSE publishes each year's list in December. When it does, save the JSON from
https://www.nseindia.com/api/holiday-master?type=trading in your browser and run

    python market_calendar_indian.py import <saved-file.json>

which writes nse_holidays.json next to this file. A year with no holiday list
is never silently treated as holiday-free: the status text says it is missing.
"""

import datetime
import json
import os
import sys

# IST offset from UTC: exactly +5 hours 30 minutes (no Daylight Saving Time in India)
IST_OFFSET_MINUTES = 330
OPEN_TIME = datetime.time(9, 15)
CLOSE_TIME = datetime.time(15, 30)
SQUARE_OFF_TIME = datetime.time(15, 15)

ROOT = os.path.dirname(os.path.abspath(__file__))
HOLIDAY_FILE = os.path.join(ROOT, "nse_holidays.json")

# NSE capital-market trading holidays for 2026 (official list, weekend dates included).
NSE_HOLIDAYS_2026 = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-21": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat trading session only)",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

_cache = {"mtime": None, "holidays": {}}


def _cached_holidays(path=None):
    """Holidays saved by `import`, re-read only when the file changes."""
    path = path or HOLIDAY_FILE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _cache["mtime"] != (path, mtime):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            holidays = data.get("holidays", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            holidays = {}
        _cache["mtime"] = (path, mtime)
        _cache["holidays"] = holidays
    return _cache["holidays"]


def all_holidays():
    """Built-in list plus anything `import` has saved (the saved list wins)."""
    merged = dict(NSE_HOLIDAYS_2026)
    merged.update(_cached_holidays())
    return merged


def holiday_name(day):
    """Name of the holiday on this date, or None if it is not a listed holiday."""
    return all_holidays().get(day.strftime("%Y-%m-%d"))


def has_holiday_list(year):
    prefix = "%04d-" % year
    return any(key.startswith(prefix) for key in all_holidays())


def is_trading_day(day):
    return day.weekday() < 5 and holiday_name(day) is None


def to_ist(utc_dt=None):
    """Converts UTC datetime to Indian Standard Time (IST)"""
    if utc_dt is None:
        utc_dt = datetime.datetime.now(datetime.timezone.utc)
    naive = utc_dt.replace(tzinfo=None)
    return naive + datetime.timedelta(minutes=IST_OFFSET_MINUTES)


def is_market_open(ist_dt=None):
    """Checks if NSE/BSE is currently open for normal trading"""
    if ist_dt is None:
        ist_dt = to_ist()

    # Check weekend (5 = Saturday, 6 = Sunday)
    if ist_dt.weekday() >= 5:
        return False, "Market is closed: Weekend"

    # Check holiday
    name = holiday_name(ist_dt)
    if name:
        return False, f"Market is closed: {name}"

    curr_time = ist_dt.time()
    if curr_time < OPEN_TIME:
        return False, f"Pre-market: NSE/BSE opens at 09:15 IST (Current: {curr_time.strftime('%H:%M')})"
    if curr_time >= CLOSE_TIME:
        return False, f"Post-market: NSE/BSE closed at 15:30 IST (Current: {curr_time.strftime('%H:%M')})"

    if not has_holiday_list(ist_dt.year):
        return True, ("NSE/BSE hours are OPEN, but no %d holiday list is loaded: confirm today is a "
                      "trading day and import NSE's list with `python market_calendar_indian.py import <file>`" % ist_dt.year)
    return True, "NSE/BSE is OPEN"


def next_market_open(ist_dt=None):
    """Computes the next trading session open timestamp"""
    if ist_dt is None:
        ist_dt = to_ist()

    if ist_dt.time() < OPEN_TIME and is_trading_day(ist_dt):
        return datetime.datetime.combine(ist_dt.date(), OPEN_TIME)

    day = ist_dt.date() + datetime.timedelta(days=1)
    while not is_trading_day(day):
        day += datetime.timedelta(days=1)
    return datetime.datetime.combine(day, OPEN_TIME)


def parse_nse_holidays(payload):
    """Turn NSE's holiday-master JSON into {"YYYY-MM-DD": "name"} (CM = capital market)."""
    holidays = {}
    for row in (payload or {}).get("CM", []):
        try:
            day = datetime.datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, TypeError, ValueError):
            continue
        holidays[day.isoformat()] = str(row.get("description") or "Trading holiday").strip()
    return holidays


def import_holidays(source_path, path=None):
    """Save holidays from a copy of NSE's holiday list that you downloaded in your browser.

    Open https://www.nseindia.com/api/holiday-master?type=trading in a browser
    (after visiting nseindia.com), save the JSON, and pass that file here.
    """
    path = path or HOLIDAY_FILE
    with open(source_path, encoding="utf-8") as fh:
        found = parse_nse_holidays(json.load(fh))
    if not found:
        raise ValueError("no capital-market (CM) holidays found in %s" % source_path)
    merged = dict(_cached_holidays(path))
    merged.update(found)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"source": "NSE holiday-master (type=trading), imported by hand",
                   "imported_at_ist": to_ist().isoformat(timespec="seconds"),
                   "holidays": merged}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return found


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 2 and sys.argv[1] == "import":
        try:
            found = import_holidays(sys.argv[2])
        except (OSError, ValueError) as exc:
            print(f"Could not import NSE holidays: {exc}", file=sys.stderr)
            sys.exit(1)
        years = sorted({key[:4] for key in found})
        print(f"Saved {len(found)} NSE holidays for {', '.join(years)} to {HOLIDAY_FILE}")
        sys.exit(0)
    now_ist = to_ist()
    open_status, msg = is_market_open(now_ist)
    print(f"Current IST: {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Status:      {msg}")
    print(f"Next Open:   {next_market_open(now_ist).strftime('%Y-%m-%d %H:%M')} IST")
