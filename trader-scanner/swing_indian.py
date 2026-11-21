#!/usr/bin/env python3
"""Swing-trade screener for NSE stocks, with the evidence behind every setup.

Looks for stocks to BUY and hold for days to a few weeks (delivery / CNC),
across the liquid NSE stocks that have futures listed (about 200 names).

  python trader-scanner/swing_indian.py picks      today's candidates, ranked
  python trader-scanner/swing_indian.py backtest   how each setup did, after costs
  python trader-scanner/swing_indian.py refresh    re-download daily prices

Every setup is replayed over the cached history each time, so a pick is always
shown next to how that exact rule has performed: average result after costs,
the likely range, both halves of the period, and whether it beat simply
holding the same stocks for the same number of days.

Rules common to every setup:
  - Signal on a completed daily bar. Entry at the NEXT day's open.
  - A stop is always set. A gap below the stop is filled at the gap price.
  - If one day touches both stop and target, the stop is assumed first.
  - Costs per round trip: a percent of price (default 0.30%: STT, stamp duty,
    exchange fees, GST and slippage on a delivery trade) PLUS a flat rupee
    charge per sale (the depository charge, about Rs 15), which is turned into
    a percent of the position size the screener actually recommends.
  - The momentum basket is tested at the size it recommends (default 10 names,
    each stock costing no more than one position), over every possible start
    day, and a stock that stays in the basket pays no new costs.

Data: Kite Connect daily candles (needs `python trader-broker/kite.py login`),
or Yahoo Finance as a fallback. The universe is today's F&O list, so stocks
that were dropped from it in the past are missing: results are flattered a
little by that. Nothing here places an order. Not financial advice.
"""

import argparse
import csv
import datetime
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "trader-timemachine"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from backtest_indian import summarize
from market_calendar_indian import is_trading_day, to_ist

STATE = os.path.join(ROOT, "trader", "state")
DAILY_DIR = os.path.join(STATE, "daily")
INSTRUMENTS_CACHE = os.path.join(STATE, "kite_instruments.csv")
PICKS_PATH = os.path.join(ROOT, "trader", "swing_picks.json")
INSTRUMENTS_URL = "https://api.kite.trade/instruments"
NIFTY = {"symbol": "NIFTY 50", "token": 256265, "yahoo": "^NSEI"}
HISTORY_DAYS = 1500          # calendar days of daily candles (about four years)
DEFAULT_COST_PCT = 0.30
DEFAULT_FLAT_COST_INR = 15.34  # depository (DP) charge per sale, GST included; check your contract note
DEFAULT_BASKET = 10
MIN_PRICE = 50.0
MIN_TURNOVER_INR = 25e7      # 20-day average daily turnover of at least 25 crore

# Each setup is fixed in advance and deliberately simple. They are not tuned
# to the data: tuning is how a backtest ends up describing the past perfectly
# and the future not at all.
SETUPS = {
    "pullback": {
        "title": "Pullback in an uptrend",
        "rule": "Above its 200-day average, 2-day RSI below 10 (a sharp short dip in a rising stock)",
        "exit": "First close above the 5-day average, or after 10 trading days",
        "stop_atr": 3.0, "target_atr": None, "max_days": 10, "exit_above_sma5": True,
    },
    "breakout": {
        "title": "20-day breakout on volume",
        "rule": "Closes at a 20-day closing high, above its 200-day average, on 1.5x normal volume",
        "exit": "Target at 2x the risk, or after 15 trading days",
        "stop_atr": 2.0, "target_atr": 4.0, "max_days": 15, "exit_above_sma5": False,
    },
    "reclaim": {
        "title": "20-day average reclaim",
        "rule": "Closes back above its 20-day average after being below it, above its 200-day average",
        "exit": "Target at 2x the risk, or after 10 trading days",
        "stop_atr": 2.0, "target_atr": 4.0, "max_days": 10, "exit_above_sma5": False,
    },
}


# ---------------------------------------------------------------- data

def _instrument_rows():
    """Kite's public instruments list, cached for the day."""
    today = to_ist().date().isoformat()
    fresh = (os.path.isfile(INSTRUMENTS_CACHE) and datetime.date.fromtimestamp(
        os.path.getmtime(INSTRUMENTS_CACHE)).isoformat() == today)
    if not fresh:
        req = urllib.request.Request(INSTRUMENTS_URL, headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        os.makedirs(STATE, exist_ok=True)
        with open(INSTRUMENTS_CACHE, "wb") as fh:
            fh.write(raw)
    with open(INSTRUMENTS_CACHE, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_universe(rows):
    """NSE stocks that have futures listed: [{'symbol', 'token', 'name'}], sorted."""
    with_futures = {r["name"] for r in rows if r.get("segment") == "NFO-FUT"}
    stocks = {}
    for r in rows:
        if (r.get("exchange") == "NSE" and r.get("segment") == "NSE" and r.get("instrument_type") == "EQ"
                and r.get("tradingsymbol") in with_futures):
            stocks[r["tradingsymbol"]] = {"symbol": r["tradingsymbol"], "token": int(r["instrument_token"]),
                                          "name": r.get("name") or r["tradingsymbol"]}
    return [stocks[s] for s in sorted(stocks)]


def _cache_path(symbol):
    return os.path.join(DAILY_DIR, "%s.json" % symbol.replace(" ", "_").replace("&", "_and_"))


def _read_cache(symbol, today):
    try:
        with open(_cache_path(symbol), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc.get("bars") if doc.get("fetched") == today else None


def _write_cache(symbol, today, source, bars):
    os.makedirs(DAILY_DIR, exist_ok=True)
    with open(_cache_path(symbol), "w", encoding="utf-8") as fh:
        json.dump({"symbol": symbol, "fetched": today, "source": source, "bars": bars}, fh)


def _kite_daily(client, token, days):
    end = datetime.datetime.now()
    rows = client.historical_data(token, end - datetime.timedelta(days=days), end, "day")
    return [{"date": r["date"].strftime("%Y-%m-%d"), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"], "volume": r.get("volume") or 0} for r in rows]


def _yahoo_daily(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5y&interval=1d" % urllib.parse.quote(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode("utf-8"))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for t, o, h, l, c, v in zip(res.get("timestamp") or [], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c):
            continue
        day = datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
        bars.append({"date": day.strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    return bars


def _kite_client():
    sys.path.insert(0, os.path.join(ROOT, "trader-broker"))
    try:
        from kite import _load_kite
        client = _load_kite(os.path.join(STATE, "kite_session.json"))
        client.profile()  # fail now, not on stock number 1
        return client
    except Exception:
        return None


def drop_unfinished_bar(bars, now_ist):
    """During market hours today's daily bar is still forming: signals need a closed bar."""
    if bars and bars[-1]["date"] == now_ist.strftime("%Y-%m-%d") and now_ist.strftime("%H:%M") < "15:30":
        return bars[:-1]
    return bars


def load_market(force=False, source="auto", quiet=False):
    """Daily bars for the universe and for Nifty. Returns (universe, {symbol: bars}, source used)."""
    now = to_ist()
    today = now.date().isoformat()
    universe = build_universe(_instrument_rows())
    wanted = universe + [NIFTY]
    data, missing = {}, []
    for item in wanted:
        bars = None if force else _read_cache(item["symbol"], today)
        if bars is None:
            missing.append(item)
        else:
            data[item["symbol"]] = bars
    used = "cache"
    if missing:
        client = _kite_client() if source in ("auto", "kite") else None
        if client is None and source == "kite":
            raise RuntimeError("Kite session is not valid; run `python trader-broker/kite.py login`")
        used = "kite" if client else "yahoo"
        if not quiet:
            print("Downloading daily prices for %d symbols from %s..." % (len(missing), used), file=sys.stderr)
        for n, item in enumerate(missing, 1):
            try:
                if client:
                    bars = _kite_daily(client, item["token"], HISTORY_DAYS)
                    time.sleep(0.35)  # Kite allows about three history requests a second
                else:
                    bars = _yahoo_daily(item.get("yahoo") or item["symbol"] + ".NS")
                    time.sleep(0.2)
            except Exception as exc:
                if not quiet:
                    print("  skipped %s: %s" % (item["symbol"], exc), file=sys.stderr)
                continue
            _write_cache(item["symbol"], today, used, bars)
            data[item["symbol"]] = bars
            if not quiet and n % 50 == 0:
                print("  %d of %d" % (n, len(missing)), file=sys.stderr)
    data = {sym: drop_unfinished_bar(bars, now) for sym, bars in data.items()}
    return universe, data, used


# ---------------------------------------------------------------- indicators

def sma(values, n):
    out, total = [None] * len(values), 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def rsi(closes, n=2):
    """Wilder's RSI."""
    out = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        up, down = max(change, 0.0), max(-change, 0.0)
        if i <= n:
            gain += up / n
            loss += down / n
        else:
            gain = (gain * (n - 1) + up) / n
            loss = (loss * (n - 1) + down) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


def atr(bars, n=14):
    """Wilder's average true range."""
    out, value = [None] * len(bars), 0.0
    for i in range(1, len(bars)):
        tr = max(bars[i]["high"] - bars[i]["low"], abs(bars[i]["high"] - bars[i - 1]["close"]),
                 abs(bars[i]["low"] - bars[i - 1]["close"]))
        value = value + tr / n if i <= n else (value * (n - 1) + tr) / n
        if i >= n:
            out[i] = value
    return out


def indicators(bars):
    closes = [b["close"] for b in bars]
    turnover = [b["close"] * b["volume"] for b in bars]
    return {"close": closes, "sma5": sma(closes, 5), "sma20": sma(closes, 20), "sma50": sma(closes, 50),
            "sma200": sma(closes, 200), "rsi2": rsi(closes, 2), "atr": atr(bars, 14),
            "vol20": sma([b["volume"] for b in bars], 20), "turnover20": sma(turnover, 20)}


def signal(setup, bars, ind, i):
    """True when `setup` fires on the bar at index i (a completed day)."""
    if i < 200 or ind["sma200"][i] is None or ind["atr"][i] is None:
        return False
    close = ind["close"][i]
    if close < MIN_PRICE or (ind["turnover20"][i] or 0) < MIN_TURNOVER_INR:
        return False
    if close <= ind["sma200"][i]:
        return False
    if setup == "pullback":
        return ind["rsi2"][i] is not None and ind["rsi2"][i] < 10
    if setup == "breakout":
        prior_high = max(ind["close"][i - 20:i])
        avg_volume = ind["vol20"][i - 1] or 0
        return close > prior_high and avg_volume > 0 and bars[i]["volume"] >= 1.5 * avg_volume
    if setup == "reclaim":
        return (ind["sma20"][i - 1] is not None and ind["close"][i - 1] < ind["sma20"][i - 1]
                and close > ind["sma20"][i])
    raise ValueError("unknown setup: %s" % setup)


# ---------------------------------------------------------------- backtest

def simulate_trade(setup, bars, ind, i, cost_pct):
    """Trade taken on the signal at bar i: enter at the next open. None if it cannot be completed."""
    spec = SETUPS[setup]
    if i + 1 >= len(bars):
        return None
    entry = bars[i + 1]["open"]
    risk = spec["stop_atr"] * ind["atr"][i]
    stop = entry - risk
    if entry <= 0 or risk <= 0 or stop <= 0:
        return None
    target = entry + spec["target_atr"] * ind["atr"][i] if spec["target_atr"] else None
    exit_price = reason = exit_index = None
    last = min(i + spec["max_days"], len(bars) - 1)
    for j in range(i + 1, last + 1):
        bar = bars[j]
        if bar["low"] <= stop:
            exit_price, reason, exit_index = min(bar["open"], stop), "stop", j
            break
        if target is not None and bar["high"] >= target:
            exit_price, reason, exit_index = target, "target", j
            break
        if spec["exit_above_sma5"] and ind["sma5"][j] is not None and bar["close"] > ind["sma5"][j]:
            exit_price, reason, exit_index = bar["close"], "time", j
            break
    if exit_price is None:
        if last < i + spec["max_days"]:
            return None  # still open at the end of the data: not a finished trade
        exit_price, reason, exit_index = bars[last]["close"], "time", last
    gross = exit_price - entry
    costs = entry * cost_pct / 100.0
    net = gross - costs
    return {"date": bars[i + 1]["date"], "signal_date": bars[i]["date"], "exit_date": bars[exit_index]["date"],
            "side": "long", "entry": round(entry, 2), "stop": round(stop, 2), "exit": round(exit_price, 2),
            "reason": reason, "days": exit_index - i, "exit_index": exit_index,
            "gross_pts": round(gross, 2), "costs_pts": round(costs, 2), "net_pts": round(net, 2),
            "gross_r": round(gross / risk, 4), "net_r": round(net / risk, 4),
            "net_pct": round(net / entry * 100.0, 4)}


def backtest_symbol(setup, bars, cost_pct):
    ind = indicators(bars)
    trades, busy_until = [], -1
    for i in range(200, len(bars) - 1):
        if i <= busy_until or not signal(setup, bars, ind, i):
            continue
        trade = simulate_trade(setup, bars, ind, i, cost_pct)
        if trade:
            busy_until = trade["exit_index"]
            trades.append(trade)
    return trades


def holding_baseline(data, universe, avg_days, cost_pct):
    """Average result of simply holding any universe stock above its 200-day average
    for `avg_days` days, after the same costs. A setup has to beat this to mean anything."""
    total, count = 0.0, 0
    for item in universe:
        bars = data.get(item["symbol"]) or []
        if len(bars) < 260:
            continue
        closes = [b["close"] for b in bars]
        trend = sma(closes, 200)
        for i in range(200, len(bars) - 1):
            if closes[i] > trend[i] and closes[i - 1] > 0:
                total += closes[i + 1] / closes[i] - 1.0
                count += 1
    daily = total / count if count else 0.0
    return daily * avg_days * 100.0 - cost_pct


def grade(stats, edge_pct):
    """How much weight a setup's history deserves."""
    if stats["trades"] < 100:
        return "UNPROVEN", "too few past trades to judge"
    ci = stats.get("net_r_95ci") or [0, 0]
    if stats["avg_net_r"] <= 0:
        return "FAILED", "lost money after costs"
    if ci[0] <= 0 or stats["first_half_avg_net_r"] <= 0 or stats["second_half_avg_net_r"] <= 0:
        return "UNPROVEN", "positive on average but it could be luck, or one half of the period lost"
    if edge_pct <= 0:
        return "UNPROVEN", "made money, but no more than simply holding the same stocks"
    return "SUPPORTED", "positive after costs in both halves and better than simply holding"


def effective_cost_pct(cost_pct, flat_inr, position_inr):
    """Round-trip cost as a percent of one position: the percent part plus the flat rupee charge."""
    if position_inr <= 0:
        return cost_pct
    return cost_pct + 100.0 * flat_inr / position_inr


def run_backtest(data, universe, cost_pct=DEFAULT_COST_PCT, momentum_spec=None):
    report = {}
    for setup in SETUPS:
        trades = []
        for item in universe:
            bars = data.get(item["symbol"]) or []
            if len(bars) >= 260:
                for trade in backtest_symbol(setup, bars, cost_pct):
                    trades.append(dict(trade, symbol=item["symbol"]))
        trades.sort(key=lambda t: (t["date"], t["symbol"]))
        stats = summarize(trades, 0)
        stats.pop("days_tested", None)
        stats.pop("verdict", None)
        if trades:
            stats["avg_days_held"] = round(sum(t["days"] for t in trades) / len(trades), 1)
            stats["avg_net_pct"] = round(sum(t["net_pct"] for t in trades) / len(trades), 3)
            stats["holding_baseline_pct"] = round(
                holding_baseline(data, universe, stats["avg_days_held"], cost_pct), 3)
            stats["edge_over_holding_pct"] = round(stats["avg_net_pct"] - stats["holding_baseline_pct"], 3)
            by_year = {}
            for t in trades:
                by_year.setdefault(t["date"][:4], []).append(t["net_pct"])
            stats["by_year_avg_net_pct"] = {y: round(sum(v) / len(v), 3) for y, v in sorted(by_year.items())}
            stats["grade"], stats["grade_reason"] = grade(stats, stats["edge_over_holding_pct"])
        else:
            stats["grade"], stats["grade_reason"] = "UNPROVEN", "the rule never fired"
        stats.pop("profit_factor", None)  # it was in rupees per share, which mixes cheap and dear stocks
        report[setup] = stats
    calendar = [b["date"] for b in data.get(NIFTY["symbol"]) or []]
    report["momentum"] = run_momentum_backtest(data, universe, calendar, cost_pct, momentum_spec)
    return report


# ---------------------------------------------------------------- momentum basket

MOMENTUM = {
    "title": "Momentum leaders",
    "rule": "The stocks with the best return over the past 12 months, leaving out the latest month",
    "exit": "Sell after 21 trading days and re-run the screen (keep a stock only if it is still on the list)",
    # The tested rule has NO stop: a normal stop (3x ATR) wiped out the whole advantage,
    # because strong stocks swing widely. Risk is controlled by small, equal positions and
    # the exit date. The emergency stop only caps a disaster and is used for sizing.
    # top_n is the basket that is actually bought; max_price leaves out stocks where one
    # share costs more than one position (None = no limit).
    "top_n": DEFAULT_BASKET, "hold_days": 21, "stop_atr": None, "emergency_stop_atr": 5.0,
    "max_price": None,
}
REFERENCE_TOP_N = 20  # the wide basket, shown next to the traded one for comparison


def momentum_score(closes, i):
    """12-month return that skips the latest month (the standard momentum measure)."""
    if i < 252 or closes[i - 252] <= 0:
        return None
    return closes[i - 21] / closes[i - 252] - 1.0


def _prepared(data, universe):
    """Per stock: bars, indicators and a date -> index map (built once per run)."""
    out = {}
    for item in universe:
        bars = data.get(item["symbol"]) or []
        if len(bars) >= 260:
            out[item["symbol"]] = {"bars": bars, "ind": indicators(bars),
                                   "at": {b["date"]: n for n, b in enumerate(bars)}}
    return out


def momentum_ranking(prepared, date):
    """Liquid stocks trading on `date`, strongest momentum first: [(score, symbol, index)]."""
    ranked = []
    for symbol, p in prepared.items():
        i = p["at"].get(date)
        if i is None:
            continue
        ind = p["ind"]
        if ind["close"][i] < MIN_PRICE or (ind["turnover20"][i] or 0) < MIN_TURNOVER_INR or ind["atr"][i] is None:
            continue
        score = momentum_score(ind["close"], i)
        if score is not None:
            ranked.append((score, symbol, i))
    ranked.sort(reverse=True)
    return ranked


def _hold_detail(bars, atr_now, i, days, stop_atr, cost_pct, carried=False):
    """Buy at the next open, sell at the close `days` later or at the stop.
    Returns (net return, stopped out?) or None. `carried` means the stock was already held
    from the period before: no new trade, so the return runs from the last close and no
    costs are paid."""
    if i + days >= len(bars):
        return None
    entry = bars[i]["close"] if carried else bars[i + 1]["open"]
    if entry <= 0:
        return None
    stop = entry - stop_atr * atr_now if stop_atr else None
    exit_price, stopped = bars[i + days]["close"], False
    if stop is not None:
        for j in range(i + 1, i + days + 1):
            if bars[j]["low"] <= stop:
                exit_price, stopped = min(bars[j]["open"], stop), True
                break
    return exit_price / entry - 1.0 - (0.0 if carried else cost_pct / 100.0), stopped


def _hold(bars, atr_now, i, days, stop_atr, cost_pct, carried=False):
    """Net return of `_hold_detail`, or None."""
    result = _hold_detail(bars, atr_now, i, days, stop_atr, cost_pct, carried)
    return None if result is None else result[0]


def _momentum_cycle(prepared, calendar, start, spec, cost_pct):
    """One run of back-to-back holding periods beginning at calendar index `start`.
    Returns (periods, trades). Costs are paid when a stock enters the basket, not while it stays."""
    hold, top_n, max_price = spec["hold_days"], spec["top_n"], spec.get("max_price")
    periods, trades = [], []
    held_all, held_top = set(), set()
    for t in range(start, len(calendar) - hold - 1, hold):
        everyone = []
        for score, symbol, i in momentum_ranking(prepared, calendar[t]):
            p = prepared[symbol]
            plain = _hold(p["bars"], p["ind"]["atr"][i], i, hold, None, cost_pct, symbol in held_all)
            if plain is not None:
                everyone.append((symbol, i, plain))
        chosen = [(symbol, i) for symbol, i, _ in everyone
                  if not max_price or symbol in held_top or prepared[symbol]["ind"]["close"][i] <= max_price][:top_n]
        if len(everyone) < 5 * top_n or len(chosen) < top_n:
            held_all, held_top = set(), set()
            continue
        top, kept, still_held = [], 0, set()
        for symbol, i in chosen:
            p = prepared[symbol]
            carried = symbol in held_top
            kept += carried
            result, stopped = _hold_detail(p["bars"], p["ind"]["atr"][i], i, hold, spec["stop_atr"], cost_pct, carried)
            top.append(result)
            if not stopped:  # a position sold at its stop has to be bought again, and pays costs again
                still_held.add(symbol)
        held_all, held_top = {symbol for symbol, _, _ in everyone}, still_held
        trades.extend(top)
        periods.append({"date": calendar[t], "top": sum(top) / len(top),
                        "all": sum(r for _, _, r in everyone) / len(everyone),
                        "replaced": 1.0 - kept / len(top)})
    return periods, trades


def run_momentum_backtest(data, universe, calendar, cost_pct=DEFAULT_COST_PCT, spec=None, with_extras=True):
    """Every `hold_days`, hold the top `top_n` by momentum; compare with holding every stock.

    The schedule is run from every possible start day (`hold_days` of them) so the result
    does not depend on which day the cycle happened to begin. Averages pool all of them;
    the t-statistic and the two halves are averaged across start days, because periods
    from different start days overlap and are not independent evidence."""
    spec = spec or MOMENTUM
    prepared = _prepared(data, universe)
    hold = spec["hold_days"]
    cycles = []
    for start in range(260, 260 + hold):
        periods, trades = _momentum_cycle(prepared, calendar, start, spec, cost_pct)
        if len(periods) >= 2:
            cycles.append((periods, trades))
    stats = {"trades": sum(len(t) for _, t in cycles), "periods": max((len(p) for p, _ in cycles), default=0),
             "start_days_tested": len(cycles), "basket": spec["top_n"], "max_price": spec.get("max_price")}
    if not cycles:
        stats["grade"], stats["grade_reason"] = "UNPROVEN", "not enough history to test"
        return stats
    t_stats, firsts, seconds, edges = [], [], [], []
    for periods, _ in cycles:
        excess = [p["top"] - p["all"] for p in periods]
        n = len(excess)
        mean = sum(excess) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in excess) / (n - 1))
        t_stats.append(mean / (sd / math.sqrt(n)) if sd > 0 else 0.0)
        firsts.append(sum(excess[:n // 2]) / (n // 2))
        seconds.append(sum(excess[n // 2:]) / (n - n // 2))
        edges.append(mean)
    pooled = [p for periods, _ in cycles for p in periods]
    all_trades = [r for _, trades in cycles for r in trades]
    n = len(pooled)
    mean = sum(p["top"] - p["all"] for p in pooled) / n
    by_year = {}
    for p in pooled:
        by_year.setdefault(p["date"][:4], []).append(p["top"] - p["all"])
    stats.update({
        "first_date": min(p[0]["date"] for p, _ in cycles), "last_date": max(p[-1]["date"] for p, _ in cycles),
        "avg_days_held": hold,
        "win_rate_pct": round(100.0 * sum(1 for r in all_trades if r > 0) / len(all_trades), 1),
        "avg_net_pct": round(100.0 * sum(p["top"] for p in pooled) / n, 3),
        "holding_baseline_pct": round(100.0 * sum(p["all"] for p in pooled) / n, 3),
        "edge_over_holding_pct": round(100.0 * mean, 3),
        "edge_range_pct": [round(100.0 * min(edges), 3), round(100.0 * max(edges), 3)],
        "t_stat": round(sum(t_stats) / len(t_stats), 2),
        "periods_beating_all_pct": round(100.0 * sum(1 for p in pooled if p["top"] > p["all"]) / n, 1),
        "first_half_edge_pct": round(100.0 * sum(firsts) / len(firsts), 3),
        "second_half_edge_pct": round(100.0 * sum(seconds) / len(seconds), 3),
        "worst_period_pct": round(100.0 * min(p["top"] for p in pooled), 2),
        "replaced_per_period_pct": round(100.0 * sum(p["replaced"] for p in pooled) / n, 1),
        "by_year_edge_pct": {y: round(100.0 * sum(v) / len(v), 3) for y, v in sorted(by_year.items())},
    })
    both_halves = stats["first_half_edge_pct"] > 0 and stats["second_half_edge_pct"] > 0
    if stats["avg_net_pct"] <= 0 or mean <= 0:
        stats["grade"], stats["grade_reason"] = "FAILED", "did no better than buying every stock"
    elif both_halves and stats["t_stat"] >= 3:
        stats["grade"], stats["grade_reason"] = "SUPPORTED", "clearly beat buying every stock, in both halves"
    elif both_halves and stats["t_stat"] >= 1.5:
        stats["grade"], stats["grade_reason"] = (
            "MODEST", "beat buying every stock in both halves, but the margin is small enough to be partly luck")
    else:
        stats["grade"], stats["grade_reason"] = "UNPROVEN", "the advantage is too small or too uneven to trust"
    if with_extras:
        keys = ("avg_net_pct", "edge_over_holding_pct", "t_stat", "worst_period_pct", "grade")
        if spec.get("emergency_stop_atr"):
            capped = run_momentum_backtest(data, universe, calendar, cost_pct,
                                           dict(spec, stop_atr=spec["emergency_stop_atr"]), False)
            stats["with_emergency_stop"] = {k: capped.get(k) for k in keys}
        if spec["top_n"] != REFERENCE_TOP_N or spec.get("max_price"):
            wide = run_momentum_backtest(data, universe, calendar, cost_pct,
                                         dict(spec, top_n=REFERENCE_TOP_N, max_price=None), False)
            stats["reference_top20"] = {k: wide.get(k) for k in keys}
    return stats


# ---------------------------------------------------------------- picks

def trading_dates_after(signal_date, hold_days):
    """(buy date, sell date): buy on the next trading day, sell at the close `hold_days`
    trading days later, counting the buy day as day one (the same count the backtest uses)."""
    day = datetime.datetime.strptime(signal_date, "%Y-%m-%d").date()
    found = []
    while len(found) < hold_days:
        day += datetime.timedelta(days=1)
        if is_trading_day(day):
            found.append(day)
    return found[0].isoformat(), found[-1].isoformat()


def market_regime(nifty_bars):
    closes = [b["close"] for b in nifty_bars]
    if len(closes) < 200:
        return {"state": "unknown", "note": "not enough Nifty history"}
    last, s50, s200 = closes[-1], sma(closes, 50)[-1], sma(closes, 200)[-1]
    if last > s50 and last > s200:
        state, note = "uptrend", "Nifty is above its 50-day and 200-day averages"
    elif last > s200:
        state, note = "mixed", "Nifty is above its 200-day average but below its 50-day average"
    else:
        state, note = "downtrend", "Nifty is below its 200-day average: long trades fail more often, size down or stand aside"
    return {"state": state, "note": note, "nifty": round(last, 2), "date": nifty_bars[-1]["date"],
            "sma50": round(s50, 2), "sma200": round(s200, 2)}


def _momentum_ranks(data, universe):
    """6-month return of each stock as a percentile of the universe (100 = strongest)."""
    returns = {}
    for item in universe:
        bars = data.get(item["symbol"]) or []
        if len(bars) > 127 and bars[-127]["close"] > 0:
            returns[item["symbol"]] = bars[-1]["close"] / bars[-127]["close"] - 1.0
    ordered = sorted(returns, key=returns.get)
    return {sym: round(100.0 * (n + 1) / len(ordered)) for n, sym in enumerate(ordered)}, returns


GRADE_ORDER = {"SUPPORTED": 0, "MODEST": 1, "UNPROVEN": 2, "FAILED": 3}
USABLE_GRADES = ("SUPPORTED", "MODEST")


def _pick(item, key, spec, grade_name, bars, ind, i, budget, max_loss, max_position_pct, extra):
    emergency = not spec.get("stop_atr")
    close, risk = bars[i]["close"], (spec.get("stop_atr") or spec["emergency_stop_atr"]) * ind["atr"][i]
    target = close + spec["target_atr"] * ind["atr"][i] if spec.get("target_atr") else None
    cap = budget * max_position_pct / 100.0
    qty = int(min(max_loss / risk, cap / close)) if risk > 0 else 0
    pick = {
        "symbol": item["symbol"], "name": item["name"], "setup": key, "setup_title": spec["title"],
        "grade": grade_name, "signal_date": bars[i]["date"], "close": round(close, 2),
        # No buy limit: every rule was tested buying at the next open, and a limit above the
        # close skipped the strongest openers. The key stays so older files still read.
        "max_entry": None,
        "stop": round(close - risk, 2), "stop_kind": "emergency" if emergency else "stop",
        "target": round(target, 2) if target else None,
        "exit_rule": spec["exit"], "risk_per_share": round(risk, 2),
        "risk_pct": round(risk / close * 100.0, 2),
        "qty": qty, "position_inr": round(qty * close, 2), "max_loss_inr": round(qty * risk, 2),
        "rsi2": round(ind["rsi2"][i], 1) if ind["rsi2"][i] is not None else None,
        "volume_x": round(bars[i]["volume"] / ind["vol20"][i - 1], 2) if ind["vol20"][i - 1] else None,
        "above_sma50": bool(ind["sma50"][i] and close > ind["sma50"][i]),
        "above_sma200_pct": round((close / ind["sma200"][i] - 1.0) * 100.0, 1) if ind["sma200"][i] else None,
        "turnover_cr": round((ind["turnover20"][i] or 0) / 1e7, 1),
    }
    pick.update(extra)
    return pick


def find_picks(data, universe, report, budget, max_loss, max_position_pct=None, spec=None):
    """Today's candidates. The momentum picks are the basket that was tested: the first
    `top_n` stocks in the ranking that one position can afford. Stronger stocks that are
    too expensive are listed with qty 0 so the user can see what was passed over."""
    spec = spec or MOMENTUM
    if max_position_pct is None:
        max_position_pct = 100.0 / spec["top_n"]
    ranks, returns = _momentum_ranks(data, universe)
    names = {u["symbol"]: u for u in universe}
    prepared = _prepared(data, universe)
    latest = max((p["bars"][-1]["date"] for p in prepared.values()), default=None)
    picks = []

    def extra(symbol):
        return {"six_month_return_pct": round(returns.get(symbol, 0.0) * 100.0, 1),
                "momentum_rank": ranks.get(symbol)}

    grade_name = report.get("momentum", {}).get("grade", "UNPROVEN")
    affordable = 0
    for place, (score, symbol, i) in enumerate(momentum_ranking(prepared, latest), 1):
        if affordable >= spec["top_n"]:
            break
        p = prepared[symbol]
        more = dict(extra(symbol), momentum_place=place, twelve_month_return_pct=round(score * 100.0, 1))
        pick = _pick(names[symbol], "momentum", spec, grade_name, p["bars"], p["ind"], i,
                     budget, max_loss, max_position_pct, more)
        affordable += pick["qty"] > 0
        picks.append(pick)

    for symbol, p in prepared.items():
        bars, ind, i = p["bars"], p["ind"], len(p["bars"]) - 1
        if bars[-1]["date"] != latest:
            continue
        for setup, spec in SETUPS.items():
            if signal(setup, bars, ind, i):
                picks.append(_pick(names[symbol], setup, spec, report.get(setup, {}).get("grade", "UNPROVEN"),
                                   bars, ind, i, budget, max_loss, max_position_pct, extra(symbol)))
    picks.sort(key=lambda k: (GRADE_ORDER[k["grade"]], k.get("momentum_place", 999), -(k["momentum_rank"] or 0)))
    return picks, latest


# ---------------------------------------------------------------- output

def _print_momentum_evidence(m):
    print()
    print(f"■ {MOMENTUM['title']}  [{m['grade']}: {m['grade_reason']}]")
    print(f"  Rule: {MOMENTUM['rule']}")
    print(f"  Exit: {MOMENTUM['exit']}")
    if m.get("periods", 0) < 2:
        return
    limit = f", each share costing at most ₹{m['max_price']:,.0f}" if m.get("max_price") else ""
    print(f"  Tested as the basket you would buy: the top {m['basket']} stocks{limit}")
    print(f"  {m['periods']} back-to-back {m['avg_days_held']}-day periods ({m['first_date']} to {m['last_date']}), "
          f"repeated from {m['start_days_tested']} different start days")
    print(f"  Basket averaged {m['avg_net_pct']:+.2f}% per period after costs; holding every stock averaged "
          f"{m['holding_baseline_pct']:+.2f}%")
    print(f"  Edge over holding every stock: {m['edge_over_holding_pct']:+.2f}% per period "
          f"({m['edge_range_pct'][0]:+.2f}% to {m['edge_range_pct'][1]:+.2f}% depending on the start day; "
          f"beat it in {m['periods_beating_all_pct']}% of periods, t = {m['t_stat']})")
    print(f"  About {m['replaced_per_period_pct']:.0f}% of the basket is replaced each period; "
          f"a stock that stays pays no new costs")
    print(f"  First half / second half edge: {m['first_half_edge_pct']:+.2f}% / {m['second_half_edge_pct']:+.2f}%"
          f" | single trades won {m['win_rate_pct']}% of the time | worst period {m['worst_period_pct']:+.2f}%")
    print("  Edge by year: " + ", ".join(f"{y} {v:+.2f}%" for y, v in m["by_year_edge_pct"].items()))
    capped = m.get("with_emergency_stop")
    if capped:
        print(f"  The tested rule has no stop. With the {MOMENTUM['emergency_stop_atr']}x ATR emergency stop the basket "
              f"averaged {capped['avg_net_pct']:+.2f}%")
        print(f"  (edge {capped['edge_over_holding_pct']:+.2f}%): the stop caps a disaster but costs part of the advantage.")
    wide = m.get("reference_top20")
    if wide and wide.get("edge_over_holding_pct") is not None:
        print(f"  For comparison, the top {REFERENCE_TOP_N} with no price limit: edge "
              f"{wide['edge_over_holding_pct']:+.2f}% per period, t = {wide['t_stat']}, grade {wide['grade']}")


def print_backtest(report, cost_pct, n_stocks, source):
    print("=" * 78)
    print("📊 SWING SETUPS ON NSE F&O STOCKS: WHAT THE HISTORY SAYS (after costs)")
    print("=" * 78)
    print(f"Stocks: {n_stocks} | Data: {source} | Costs: {cost_pct:.2f}% per round trip at your position size "
          f"| Entry: next day's open")
    _print_momentum_evidence(report["momentum"])
    for setup, spec in SETUPS.items():
        s = report[setup]
        print()
        print(f"■ {spec['title']}  [{s['grade']}: {s['grade_reason']}]")
        print(f"  Rule: {spec['rule']}")
        print(f"  Exit: {spec['exit']}; stop {spec['stop_atr']}x ATR below entry")
        if not s["trades"]:
            continue
        ci = s["net_r_95ci"]
        print(f"  Trades: {s['trades']} ({s['first_date']} to {s['last_date']}), held {s['avg_days_held']} days on average")
        print(f"  Win rate {s['win_rate_pct']}% | average {s['avg_net_pct']:+.2f}% per trade ({s['avg_net_r']:+.3f}R), "
              f"likely range {ci[0]:+.3f}R to {ci[1]:+.3f}R")
        print(f"  Simply holding for the same time: {s['holding_baseline_pct']:+.2f}% "
              f"-> edge over holding {s['edge_over_holding_pct']:+.2f}% per trade")
        print(f"  First half / second half: {s['first_half_avg_net_r']:+.3f}R / {s['second_half_avg_net_r']:+.3f}R"
              f" | exits: target {s['exits']['target']}, stop {s['exits']['stop']}, rule or time {s['exits']['time']}")
        print("  By year (avg % per trade): " + ", ".join(
            f"{y} {v:+.2f}%" for y, v in s["by_year_avg_net_pct"].items()))
    print()
    print("The universe is today's F&O list, so stocks dropped from it in the past are missing,")
    print("which flatters every number a little. Several rules were tried before these were kept,")
    print("so some of any apparent edge is luck. Past results do not guarantee future ones.")


def print_picks(picks, latest, regime, report, budget, max_loss, limit, dates=None):
    print("=" * 78)
    print(f"🎯 SWING CANDIDATES (signals from the close of {latest})")
    print("=" * 78)
    print(f"Market: {regime['note']}" + (f" (Nifty {regime['nifty']:,.2f})" if "nifty" in regime else ""))
    m = report["momentum"]
    basket = m.get("basket") or MOMENTUM["top_n"]
    print(f"Sizing: ₹{budget:,.0f} capital in {basket} equal positions of about ₹{budget / basket:,.0f}, "
          f"at most ₹{max_loss:,.0f} lost per trade")
    if dates:
        print(f"Momentum timing: buy on {dates[0]}, sell at the close on {dates[1]}, then run this again")
    print("Evidence behind each rule (after costs):")
    line = f"  {MOMENTUM['title']}: {m['grade']}"
    if m.get("periods", 0) >= 2:
        line += (f" (basket of {basket}: {m['avg_net_pct']:+.2f}% per {m['avg_days_held']} days, "
                 f"{m['edge_over_holding_pct']:+.2f}% versus holding every stock)")
    print(line)
    for setup, spec in SETUPS.items():
        s = report[setup]
        line = f"  {spec['title']}: {s['grade']}"
        if s["trades"]:
            line += (f" ({s['avg_net_pct']:+.2f}% per trade, "
                     f"{s['edge_over_holding_pct']:+.2f}% versus just holding)")
        print(line)
    usable = [p for p in picks if p["grade"] in USABLE_GRADES]
    shown = usable[:limit]
    if not shown:
        print()
        print("No rule has enough evidence behind it right now, so there is nothing to recommend.")
        print("Doing nothing is a valid decision.")
    for n, p in enumerate(shown, 1):
        print()
        print(f"{n}. {p['symbol']} ({p['name']})  [{p['setup_title']}: {p['grade']}]")
        stop_word = "emergency stop" if p["stop_kind"] == "emergency" else "stop"
        print(f"   Close ₹{p['close']:,.2f} | buy at the next open | {stop_word} ₹{p['stop']:,.2f} "
              f"({p['risk_pct']}% below)" + (f" | target ₹{p['target']:,.2f}" if p["target"] else ""))
        print(f"   Exit: {p['exit_rule']}")
        if p["qty"]:
            print(f"   Size: {p['qty']} shares = ₹{p['position_inr']:,.0f}, loss at the stop ₹{p['max_loss_inr']:,.0f}")
        else:
            print("   Size: 0 shares (one share costs more than one position, or risks more than your max loss): passed over")
        detail = f"   6-month return {p['six_month_return_pct']:+.1f}%"
        if "twelve_month_return_pct" in p:
            detail = (f"   Momentum #{p['momentum_place']}: 12-month return (skipping the latest month) "
                      f"{p['twelve_month_return_pct']:+.1f}%, 6-month {p['six_month_return_pct']:+.1f}%")
        print(detail + f" | {'above' if p['above_sma50'] else 'BELOW'} its 50-day average | "
                       f"turnover ₹{p['turnover_cr']:,.0f} cr/day")
    rest = len(usable) - len(shown)
    others = [p for p in picks if p["grade"] not in USABLE_GRADES]
    if rest > 0:
        print()
        print(f"{rest} more candidate(s) from the same rule: raise --limit to see them.")
    if others:
        symbols = sorted({p["symbol"] for p in others})
        print()
        print(f"{len(others)} signal(s) from rules without evidence are not recommended (saved in the JSON): "
              + ", ".join(symbols[:15]) + (" ..." if len(symbols) > 15 else ""))
    print()
    print(f"The momentum grade is for the whole basket of {basket} bought together at the open; owning")
    print("only some of them is a different, untested bet. Before buying: check for results or other")
    print("news due in the holding period, and pass the risk check.")
    print("These are candidates from a rule, not predictions. Not financial advice.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Swing-trade screener for NSE stocks, with backtested evidence")
    p.add_argument("command", choices=("picks", "backtest", "refresh"), nargs="?", default="picks")
    p.add_argument("--source", choices=("auto", "kite", "yahoo"), default="auto")
    p.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT,
                   help="Round-trip costs that scale with price (taxes, fees, slippage), percent")
    p.add_argument("--flat-cost", type=float,
                   help="Flat rupee cost per round trip, such as the depository charge on a sale "
                        "(default: swing_flat_cost_inr in config_indian.json, else %.2f)" % DEFAULT_FLAT_COST_INR)
    p.add_argument("--basket", type=int,
                   help="How many momentum stocks to hold, in equal positions "
                        "(default: swing_basket in config_indian.json, else %d)" % DEFAULT_BASKET)
    p.add_argument("--budget", type=float, help="Capital in rupees (default: budget_inr in config_indian.json)")
    p.add_argument("--max-loss", type=float, help="Most to lose on one trade (default: config_indian.json)")
    p.add_argument("--limit", type=int, default=10, help="How many candidates to show")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        with open(os.path.join(ROOT, "config_indian.json"), encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        config = {}
    budget = args.budget or float(config.get("budget_inr", 50000))
    max_loss = args.max_loss or float(config.get("max_loss_per_trade_inr", 2000))
    basket = args.basket or int(config.get("swing_basket", DEFAULT_BASKET))
    if basket < 1:
        p.error("--basket must be at least 1")
    flat_cost = float(config.get("swing_flat_cost_inr", DEFAULT_FLAT_COST_INR)) if args.flat_cost is None else args.flat_cost
    position = budget / basket
    cost_pct = round(effective_cost_pct(args.cost_pct, flat_cost, position), 3)
    spec = dict(MOMENTUM, top_n=basket, max_price=position)

    try:
        universe, data, source = load_market(force=args.command == "refresh", source=args.source, quiet=args.json)
    except Exception as exc:
        print("swing_indian.py: could not load prices: %s" % exc, file=sys.stderr)
        return 1
    loaded = [u for u in universe if len(data.get(u["symbol"]) or []) >= 260]
    if args.command == "refresh":
        print("Daily prices ready for %d of %d stocks (source: %s)." % (len(loaded), len(universe), source))
        return 0
    if not loaded:
        print("swing_indian.py: no price history could be loaded", file=sys.stderr)
        return 1

    costs = {"cost_pct": cost_pct, "percent_part": args.cost_pct, "flat_inr": flat_cost,
             "position_inr": round(position, 2)}
    report = run_backtest(data, universe, cost_pct, spec)
    if args.command == "backtest":
        if args.json:
            print(json.dumps({"stocks": len(loaded), "cost_pct": cost_pct, "costs": costs, "setups": report}, indent=2))
        else:
            print_backtest(report, cost_pct, len(loaded), source)
        return 0

    regime = market_regime(data.get(NIFTY["symbol"]) or [])
    picks, latest = find_picks(data, universe, report, budget, max_loss, spec=spec)
    dates = trading_dates_after(latest, spec["hold_days"])
    doc = {"generated_at_ist": to_ist().isoformat(timespec="seconds"), "signal_date": latest,
           "momentum_buy_date": dates[0], "momentum_sell_date": dates[1],
           "market": regime, "budget_inr": budget, "max_loss_per_trade_inr": max_loss,
           "basket": basket, "hold_days": spec["hold_days"], "cost_pct": cost_pct, "costs": costs,
           "setups": report,
           "picks": picks}
    os.makedirs(os.path.dirname(PICKS_PATH), exist_ok=True)
    with open(PICKS_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print_picks(picks, latest, regime, report, budget, max_loss, args.limit, dates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
