#!/usr/bin/env python3
"""News for NSE stocks and the Indian market. Standard library only.

    python trader-news/news_indian.py                          # the swing basket
    python trader-news/news_indian.py --tickers MCX BHEL       # these NSE stocks
    python trader-news/news_indian.py --tickers MCX --all --hours 168
    python trader-news/news_indian.py --market                 # Nifty, Bank Nifty, Sensex headlines
    python trader-news/news_indian.py --keywords rbi "bank nifty" --limit 10

Stocks, when --tickers is not given: the basket being monitored
(trader/swing_watch.json) and the basket from the latest screen
(trader/swing_picks.json). Symbols are NSE symbols (MCX, BAJAJ-AUTO); add .BO
for a BSE-only stock. With no stocks anywhere it falls back to market mode.

Per stock, one request each:
  - The move and the company's full name: Yahoo Finance's chart for SYMBOL.NS
    (unofficial, can lag), the last price against the previous close.
  - Headlines: a Google News search (India edition) for the company's name or
    "SYMBOL share(s)". A story is kept only when its headline names the company
    or the symbol; the others are counted in a note and left out. When a company
    is known by a short name its full name does not start with, say so:
    --name SUNPHARMA="Sun Pharma".

Company filings (results, board meetings, block deals, pledges) are NOT read:
NSE and BSE refuse automated requests. Open the company's page on NSE before
acting; the output says where.

Market mode (--market or --keywords) reads the Moneycontrol and Economic Times
market feeds and keeps the headlines that match the keywords. It suits index
and macro news; single companies rarely show up there, so use --tickers.

Times print in India time (IST). State: trader/state/news_indian.json
remembers what you have seen (30 days), so a story shows once. Exit code 1
means nothing new. --offline DIR reads chart-<SYMBOL>.NS.json and
gnews-<SYMBOL>.xml from DIR; the tests use it.

Fetching, the price line, tagging and the seen-state come from news.py in this
folder (the US tool), so both tools behave the same way.

Headlines are leads, not facts: open the story before acting. Not financial advice.
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import news  # noqa: E402  (the shared engine in this folder)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
NSE_PAGE = "https://www.nseindia.com/get-quotes/equity?symbol=%s"
IST = _dt.timedelta(hours=5, minutes=30)
PER_STOCK = 6
STOPWORDS = {"of", "and", "&", "the", "for", "in"}
LEGAL_SUFFIX = re.compile(r"[\s,]+(?:limited|ltd\.?|pvt\.?|private)$", re.I)
# Price-quote and ratings pages that search results carry as if they were stories
QUOTE_PAGE = re.compile(r"Stock Price (?:&|and) Chart|Share Price - Live|\|\s*StockIQ|Stock Price, News, Quote"
                        r"|Seasonal returns chart|Share Price Today - .* on NSE/BSE|^\S+(?: \S+){0,3} Share Price$",
                        re.I)

# Topics as Indian market headlines word them. Searched case-insensitively.
KEYWORDS = [
    ("earnings", r"\bresults?\b|\bearnings\b|\bQ[1-4]\b|\bprofit\b|\brevenue\b|\bguidance\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|\btarget\b|\bbuy rating\b|\bsell rating\b"
                r"|\boutperform\b|\bunderperform\b|\bbrokerages?\b"),
    ("legal", r"\bcourt\b|\bNCLT\b|\blawsuit\b|\bprobe\b|\binvestigation\b|\bfraud\b|\braids?\b"
              r"|\bEnforcement Directorate\b|\bCBI\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bdemerger\b|\bstake\b|\bjoint venture\b"
             r"|\borders?\b|\bbags\b|\bcontracts?\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bstock split\b|\bQIP\b|\bOFS\b|\brights issue\b"
                r"|\bfund ?rais|\bblock deal\b|\bbulk deal\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bchairman\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\bdefault\b|\bpledge[ds]?\b|\bauditor\b|\bimpairment\b|\bdelist|\bfire\b|\bshutdown\b"),
    ("halt", r"\bupper circuit\b|\blower circuit\b|\bsuspen(?:d|sion)\b"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bUSFDA\b|\bFDA\b|\bwarning letter\b|\bapprovals?\b|\bban\b"),
    ("macro", r"\bNifty\b|\bSensex\b|\bFIIs?\b|\bDIIs?\b|\brupee\b|\binflation\b|\brepo\b|\bcrude\b"),
]

# ---------------------------------------------------------------- stocks


def nse_yahoo(symbol):
    """Yahoo's symbol for an NSE stock: MCX -> MCX.NS (a .NS or .BO suffix is kept)."""
    s = symbol.strip().upper()
    return s if "." in s else s + ".NS"


def plain(symbol):
    s = symbol.upper()
    return s[:-3] if s.endswith((".NS", ".BO")) else s


def watch_from_swing(watch="trader/swing_watch.json", picks="trader/swing_picks.json"):
    """{SYMBOL: name or None}: the monitored basket, then the latest screen's basket."""
    out = {}
    for p in (news.load_json(watch) or {}).get("positions", []):
        if p.get("symbol"):
            out[p["symbol"].upper()] = p.get("name")
    for p in (news.load_json(picks) or {}).get("picks", []):
        if p.get("setup") == "momentum" and (p.get("qty") or 0) > 0 and p.get("symbol"):
            out.setdefault(p["symbol"].upper(), p.get("name"))
    return out


def clean_name(name):
    """Company name without "The" in front or "Limited" behind: The Federal Bank Limited -> Federal Bank."""
    name = re.sub(r"^the\s+", "", (name or "").strip(), flags=re.I)
    while LEGAL_SUFFIX.search(name):
        name = LEGAL_SUFFIX.sub("", name).strip()
    return name


def key_phrase(name):
    """The words a headline uses for the company: the first two words of its name,
    longer when the second is a joining word (Bank of Maharashtra, Larsen & Toubro)."""
    words = clean_name(name).split()
    if not words:
        return ""
    n = min(2, len(words))
    while n < len(words) and words[n - 1].lower() in STOPWORDS:
        n += 1
    return " ".join(words[:n])


def gnews_query(symbol, name, days):
    terms = ['"%s share"' % symbol, '"%s shares"' % symbol]
    key = key_phrase(name)
    if key and key.lower() != symbol.lower():
        terms.insert(0, '"%s"' % key)
    return "%s when:%dd" % (" OR ".join(terms), max(1, days))


def headline_names(symbol, name):
    """Regex that matches a headline naming the company or its symbol."""
    alts = [r"\b%s\b" % re.escape(symbol)]
    key = key_phrase(name)
    if key:
        # whole words, separated by spaces: "Multi Commodity" but not "multi-commodity miner"
        alts.append(r"(?<![\w-])%s(?![\w-])" % r"\s+".join(re.escape(w) for w in key.split()))
    return re.compile("|".join(alts), re.I)


def parse_gnews(data, ticker):
    """Google News search RSS -> items, with the publisher as the source."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise news.NewsError("Google News for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = news._text(it, "title")
        source = news._text(it, "source") or "Google News"
        if title.endswith(" - " + source):
            title = title[: -len(source) - 3].rstrip()
        link = news._text(it, "link")
        out.append({"id": "gn:" + (news._text(it, "guid") or link), "source": source,
                    "kind": "headline", "ticker": ticker, "title": title, "summary": "",
                    "link": link, "time": news.parse_time(news._text(it, "pubDate"))})
    return out


def collect_stocks(fetcher, watch, days, notes, names=None):
    """watch: {SYMBOL: name or None}, updated with Yahoo's full names unless `names`
    ({SYMBOL: phrase}, from --name) says what to search for. Returns (items, moves)."""
    names = names or {}
    yahoo = {nse_yahoo(s): s for s in watch}
    moves = news.collect_moves(fetcher, {y: None for y in yahoo}, notes)
    for m in moves:
        m["ticker"] = yahoo[m["ticker"]]
        if m.get("name"):
            watch[m["ticker"]] = m["name"]  # the full name searches better than a broker's short one
    watch.update({s: n for s, n in names.items() if s in watch})
    items, left_out = [], {}
    for sym in sorted(watch):
        url = GNEWS % urllib.parse.quote(gnews_query(plain(sym), watch[sym], days))
        try:
            found = parse_gnews(fetcher.get(url, "gnews-%s.xml" % plain(sym)), sym)
        except news.NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                notes.append("headlines for %s: %s" % (sym, exc))
            continue
        rx = headline_names(plain(sym), watch[sym])
        named = [i for i in found if rx.search(i["title"]) and not QUOTE_PAGE.search(i["title"])]
        if len(found) > len(named):
            left_out[sym] = len(found) - len(named)
        items += named
    if left_out:
        notes.append("left out %d stor%s that do not name the company or are price-quote pages (%s)" % (
            sum(left_out.values()), "y" if sum(left_out.values()) == 1 else "ies",
            ", ".join("%s %d" % kv for kv in sorted(left_out.items()))))
    return items, moves


def cap_per_stock(items, per):
    """The newest `per` stories for each stock (items are newest first)."""
    count, out = {}, []
    for it in items:
        n = count.get(it["ticker"], 0)
        if n < per:
            out.append(it)
        count[it["ticker"]] = n + 1
    hidden = sum(max(0, n - per) for n in count.values())
    return out, hidden


def ist(utc):
    return utc.replace(tzinfo=None) + IST


def render_stocks(items, moves, notes, now, move_pct=news.MOVE_PCT):
    out = []
    for m in sorted(moves, key=lambda m: -abs(m["pct"])):
        when = (" at %s IST" % ist(m["time"]).strftime("%d %b %H:%M")) if m.get("time") else ""
        out.append("%-11s %10s %+6.2f%% vs previous close %s%s%s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, "  MOVING" if abs(m["pct"]) >= move_pct else ""))
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s  %-11s %-18s %s" % (when, who, it["source"][:18], it["title"]))
        extra = (["tags: " + ", ".join(it["tags"])] if it["tags"] else []) + [it["link"]]
        out.append("      " + "  ".join(extra))
    for n in notes:
        out.append("note: %s" % n)
    first = next(iter(sorted({m["ticker"] for m in moves} | {i["ticker"] for i in items})), "SYMBOL")
    out.append("Company filings are not read here: check announcements on NSE before acting, "
               "for example %s" % (NSE_PAGE % plain(first)))
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def parse_names(pairs):
    """["SUNPHARMA=Sun Pharma", ...] -> {"SUNPHARMA": "Sun Pharma"}."""
    out = {}
    for pair in pairs or []:
        sym, eq, phrase = pair.partition("=")
        if not eq or not sym.strip() or not phrase.strip():
            raise SystemExit('news_indian: --name needs SYMBOL="Name", for example SUNPHARMA="Sun Pharma"')
        out[sym.strip().upper()] = phrase.strip()
    return out


def run_stocks(args, watch):
    now = news.parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = news.load_json(args.state) or {}
    notes = []
    fetcher = news.Fetcher(offline=args.offline)
    days = int((args.hours + 23) // 24)
    items, moves = collect_stocks(fetcher, watch, days, notes, parse_names(args.name))
    names = {s: key_phrase(n) or None for s, n in watch.items()}
    items = news.dedupe(news.tag(items, names, KEYWORDS))
    shown, hidden = cap_per_stock(news.select(items, state, now, hours=args.hours, show_all=args.all),
                                  args.per_stock)
    if hidden:
        notes.append("%d older stor%s not shown (at most %d per stock; raise --per-stock)" % (
            hidden, "y" if hidden == 1 else "ies", args.per_stock))
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": news._json_ready(shown),
                          "notes": notes}, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_stocks(shown, moves, notes, now, args.move_pct))
    if not args.dry_run:
        news.remember(shown, state, now)  # only what was shown, so a capped story can show later
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


# ---------------------------------------------------------------- market headlines

FEEDS = {
    "moneycontrol_market": "https://www.moneycontrol.com/rss/marketreports.xml",
    "moneycontrol_latest": "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977082108.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2143846026.cms",
}
MARKET_KEYWORDS = ["nifty", "bank nifty", "sensex"]
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return ET.fromstring(resp.read())
    except Exception as e:
        sys.stderr.write("Warning: Failed to fetch %s: %s\n" % (url, e))
        return None


def parse_items(root, source_name):
    items = []
    if root is None:
        return items
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        description = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()
        if title:
            items.append({"title": title, "link": item.findtext("link", "").strip(),
                          "pub_date": item.findtext("pubDate", "").strip(),
                          "summary": description, "source": source_name})
    return items


def filter_news(items, keywords):
    if not keywords:
        return items
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    return [it for it in items if pattern.search(it["title"]) or pattern.search(it["summary"])]


def run_market(keywords, limit, as_json):
    all_items = []
    for name, url in FEEDS.items():
        all_items.extend(parse_items(fetch_feed(url), name))
    seen, results = set(), []
    for item in filter_news(all_items, keywords):
        if item["title"].lower() not in seen:
            seen.add(item["title"].lower())
            results.append(item)
    results = results[:limit]
    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    print("=" * 70)
    print("INDIAN MARKET HEADLINES (Moneycontrol & Economic Times): " + ", ".join(keywords))
    print("=" * 70)
    if not results:
        print("No matching headlines found right now.")
        return 0
    for idx, item in enumerate(results, 1):
        print("\n%d. %s" % (idx, item["title"]))
        if item.get("pub_date"):
            print("   Published: %s | Source: %s" % (item["pub_date"], item["source"]))
        if item.get("summary"):
            s = item["summary"]
            print("   Summary: " + (s[:160] + "..." if len(s) > 160 else s))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="NSE symbols (default: the swing basket)")
    ap.add_argument("--market", action="store_true", help="market headlines instead of stocks")
    ap.add_argument("--keywords", nargs="+", help="market mode: keep headlines with these words")
    ap.add_argument("--limit", type=int, default=10, help="market mode: how many headlines")
    ap.add_argument("--name", action="append", metavar='SYMBOL="Name"',
                    help='what headlines call a company, when its full name does not fit '
                         '(for example SUNPHARMA="Sun Pharma"); repeat for more')
    ap.add_argument("--per-stock", type=int, default=PER_STOCK, help="newest stories shown per stock")
    ap.add_argument("--hours", type=float, default=48, help="ignore stories older than this")
    ap.add_argument("--all", action="store_true", help="show stories already seen too")
    ap.add_argument("--move-pct", type=float, default=news.MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--watch", default="trader/swing_watch.json")
    ap.add_argument("--picks", default="trader/swing_picks.json")
    ap.add_argument("--state", default="trader/state/news_indian.json")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.market or args.keywords:
        return run_market(args.keywords or MARKET_KEYWORDS, args.limit, args.json)
    if args.tickers:
        known = watch_from_swing(args.watch, args.picks)
        watch = {t.upper(): known.get(t.upper()) for t in args.tickers}
    else:
        watch = watch_from_swing(args.watch, args.picks)
    if not watch:
        print("news_indian: no stocks in trader/swing_watch.json or trader/swing_picks.json; "
              "showing market headlines. Pass --tickers for stocks.", file=sys.stderr)
        return run_market(MARKET_KEYWORDS, args.limit, args.json)
    return run_stocks(args, watch)


if __name__ == "__main__":
    sys.exit(main())
