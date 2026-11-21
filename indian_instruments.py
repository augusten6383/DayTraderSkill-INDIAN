#!/usr/bin/env python3
"""Index underlyings and exchange lot sizes for the Indian tools. Standard library only.

Lot sizes change (NSE and BSE revise them a few times a year), so they live in
config_indian.json rather than in code. Refresh them from Kite's public
instruments list (no login needed):

    python indian_instruments.py refresh

A lot size can differ by expiry while a revision is phasing in. `refresh`
stores the lot of the nearest expiry; always check the contract you trade.
"""

import csv
import datetime
import gzip
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config_indian.json")
INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# Longest names first, so BANKNIFTY is never read as NIFTY.
INDEX_NAMES = ("BANKNIFTY", "SENSEX", "NIFTY")
ALIASES = {"NIFTYBANK": "BANKNIFTY", "NIFTY50": "NIFTY", "^NSEI": "NIFTY",
           "^NSEBANK": "BANKNIFTY", "^BSESN": "SENSEX"}
# An index name on its own, or followed by an expiry (which starts with a digit).
_CONTRACT = re.compile(r"^(%s)(\d.*)?$" % "|".join(INDEX_NAMES))

FALLBACK_LOTS = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}


def underlying_of(symbol):
    """'BANKNIFTY26NOV52000CE' -> 'BANKNIFTY'; a stock or unknown index -> None."""
    clean = re.sub(r"[\s_-]", "", str(symbol or "").upper())
    if clean in ALIASES:
        return ALIASES[clean]
    match = _CONTRACT.match(clean)
    return match.group(1) if match else None


def load_config(path=None):
    try:
        with open(path or CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def lot_size_for(symbol, config=None):
    """Exchange lot for an index contract; 1 for anything that is not a known index."""
    name = underlying_of(symbol)
    if name is None:
        return 1
    if config is None:
        config = load_config()
    lot = (config.get("indices", {}).get(name) or {}).get("lot_size")
    try:
        lot = int(lot)
    except (TypeError, ValueError):
        lot = 0
    return lot if lot > 0 else FALLBACK_LOTS[name]


def parse_lot_sizes(rows, today=None):
    """Nearest-expiry lot size per index from rows of Kite's instruments CSV."""
    today = today or datetime.date.today().isoformat()
    best = {}
    for row in rows:
        name = row.get("name")
        if name not in INDEX_NAMES or row.get("segment") not in ("NFO-OPT", "BFO-OPT"):
            continue
        expiry = row.get("expiry") or ""
        try:
            lot = int(row.get("lot_size") or 0)
        except ValueError:
            continue
        if lot <= 0 or expiry < today:
            continue
        if name not in best or expiry < best[name][0]:
            best[name] = (expiry, lot)
    return {name: {"lot_size": lot, "expiry": expiry} for name, (expiry, lot) in best.items()}


def fetch_lot_sizes():
    req = urllib.request.Request(INSTRUMENTS_URL, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return parse_lot_sizes(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def refresh(path=None):
    path = path or CONFIG_PATH
    found = fetch_lot_sizes()
    missing = [name for name in INDEX_NAMES if name not in found]
    if missing:
        raise ValueError("Kite's instruments list has no option contracts for: %s" % ", ".join(missing))
    config = load_config(path)
    changes = []
    for name, info in found.items():
        entry = config.setdefault("indices", {}).setdefault(name, {})
        if entry.get("lot_size") != info["lot_size"]:
            changes.append("%s %s -> %s" % (name, entry.get("lot_size"), info["lot_size"]))
        entry["lot_size"] = info["lot_size"]
    config["lot_sizes_as_of"] = datetime.date.today().isoformat()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return found, changes


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        try:
            lots, changed = refresh()
        except Exception as exc:
            print("Could not refresh lot sizes: %s" % exc, file=sys.stderr)
            sys.exit(1)
        for index_name in sorted(lots):
            print("%-10s lot %3d (expiry %s)" % (index_name, lots[index_name]["lot_size"],
                                                 lots[index_name]["expiry"]))
        print("Changed: %s" % (", ".join(changed) if changed else "nothing"))
    else:
        cfg = load_config()
        for index_name in INDEX_NAMES:
            print("%-10s lot %d" % (index_name, lot_size_for(index_name, cfg)))
        print("Lot sizes as of: %s" % cfg.get("lot_sizes_as_of", "unknown"))
