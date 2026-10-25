#!/usr/bin/env python3
"""Indian Financial Market News Monitor for trader-news. Standard library only.

Fetches real-time Indian stock market headlines, corporate actions, and F&O news
from official RSS feeds:
  - Moneycontrol Market Reports & Headlines
  - Economic Times (ET) Markets & F&O news
  - LiveMint Markets
Filters specifically for NIFTY, BANK NIFTY, SENSEX, or specific Indian watchlist stocks.
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = {
    "moneycontrol_market": "https://www.moneycontrol.com/rss/marketreports.xml",
    "moneycontrol_latest": "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977082108.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2143846026.cms"
}

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            return ET.fromstring(content)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to fetch {url}: {e}\n")
        return None

def parse_items(root, source_name):
    items = []
    if root is None:
        return items
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        description = item.findtext("description", "").strip()
        
        # Clean HTML tags from description if any
        description = re.sub(r"<[^>]+>", "", description).strip()
        
        if title:
            items.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "summary": description,
                "source": source_name
            })
    return items

def filter_news(items, keywords):
    if not keywords:
        return items
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    return [it for it in items if pattern.search(it["title"]) or pattern.search(it["summary"])]

def main():
    parser = argparse.ArgumentParser(description="Indian Market News Monitor")
    parser.add_argument("--keywords", nargs="+", default=["nifty", "bank nifty", "sensex"],
                        help="Keywords/tickers to filter (default: nifty bank nifty sensex)")
    parser.add_argument("--limit", type=int, default=10, help="Number of headlines to show")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    all_items = []
    for name, url in FEEDS.items():
        tree = fetch_feed(url)
        all_items.extend(parse_items(tree, name))

    filtered = filter_news(all_items, args.keywords)
    # Deduplicate by title
    seen = set()
    deduped = []
    for item in filtered:
        clean_title = item["title"].lower()
        if clean_title not in seen:
            seen.add(clean_title)
            deduped.append(item)

    results = deduped[:args.limit]

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("=" * 70)
    print("🇮🇳 INDIAN FINANCIAL MARKET NEWS (Moneycontrol & Economic Times)")
    print("=" * 70)
    if not results:
        print("No matching headlines found right now.")
        return

    for idx, item in enumerate(results, 1):
        print(f"\n{idx}. {item['title']}")
        if item.get("pub_date"):
            print(f"   Published: {item['pub_date']} | Source: {item['source']}")
        if item.get("summary"):
            summary_snip = item['summary'][:160] + "..." if len(item['summary']) > 160 else item['summary']
            print(f"   Summary: {summary_snip}")

if __name__ == "__main__":
    main()
