#!/usr/bin/env python3
"""FII / DII Institutional Activity & Sentiment Tracker. Standard library only.

Replaces US Congress trader-pelosi with Indian FII (Foreign Institutional Investors)
and DII (Domestic Institutional Investors) net buying/selling figures.
This is the single most watched macro indicator for NIFTY, BANK NIFTY, and SENSEX.
"""

import argparse
import datetime
import json
import urllib.request
import re

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_fii_dii_summary():
    """Fetches FII/DII net flow updates from financial feeds"""
    url = "https://www.moneycontrol.com/rss/marketreports.xml"
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            # Search for FII DII patterns in headlines
            matches = re.findall(r"<title>(.*?FII.*?DII.*?)</title>", content, re.IGNORECASE)
            if matches:
                return [m.replace("<![CDATA[", "").replace("]]>", "") for m in matches]
    except Exception as e:
        pass
    return []

def main():
    parser = argparse.ArgumentParser(description="Indian Market FII & DII Flow Tracker")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    reports = get_fii_dii_summary()

    data = {
        "market": "NSE/BSE",
        "indicator": "FII / DII Cash & F&O Activity",
        "latest_reports": reports if reports else ["FII/DII data updates at market close (approx. 5:30 PM IST daily)."]
    }

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print("=" * 65)
    print("🏛️ INSTITUTIONAL FLOW TRACKER (FII / DII ACTIVITY)")
    print("=" * 65)
    for rep in data["latest_reports"]:
        print(f"• {rep}")

if __name__ == "__main__":
    main()
