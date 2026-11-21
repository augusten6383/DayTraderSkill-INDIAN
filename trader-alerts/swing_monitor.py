#!/usr/bin/env python3
"""Swing basket monitor: progress, health and decisions for the stocks picked by
trader-scanner/swing_indian.py, written as an HTML report and emailed.

  python trader-alerts/swing_monitor.py init          start watching today's top picks
  python trader-alerts/swing_monitor.py run           build the report, save it, email it
  python trader-alerts/swing_monitor.py run --no-email
  python trader-alerts/swing_monitor.py test-email    check the email settings

What each report says, per stock: where it is against the planned buy price,
today's move, how it compares with Nifty over the same days, how far it is from
the emergency stop, which day of the plan it is, whether it is still in
the momentum basket, and the one decision (if any) that is due.

Prices come from Yahoo Finance and can lag the exchange by a few minutes.
Profit and loss assumes the planned quantity bought at the buy-date open,
unless you record your real fills in trader/swing_watch.json
("actual_entry" and "actual_qty"). Set "actual_qty" to 0 for a stock you skipped.

Email settings (settings.json, or the environment variables in brackets):
  email_to       [EMAIL_TO]       where to send the report
  smtp_user      [SMTP_USER]      the sending account
  smtp_password  [SMTP_PASSWORD]  an app password for that account, never your main password
  smtp_host      [SMTP_HOST]      default smtp.gmail.com
  smtp_port      [SMTP_PORT]      default 587

Nothing here places or cancels an order. Not financial advice.
"""

import argparse
import datetime
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "trader-scanner"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import swing_indian as swing
from market_calendar_indian import holiday_name, is_trading_day, to_ist

PICKS_PATH = os.path.join(ROOT, "trader", "swing_picks.json")
WATCH_PATH = os.path.join(ROOT, "trader", "swing_watch.json")
RANK_PATH = os.path.join(ROOT, "trader", "state", "swing_rank.json")
REPORT_DIR = os.path.join(ROOT, "trader", "reports")
SETTINGS_PATH = os.path.join(ROOT, "settings.json")
NEAR_STOP_PCT = 4.0   # warn when the price is within this percent of the emergency stop
RANK_AFTER = "15:35"  # refresh the momentum ranking once the day's bar is complete


# ---------------------------------------------------------------- files

def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def build_watch(picks_doc, top, until=None):
    """Watch list from a swing_picks.json document: the first `top` usable momentum picks."""
    chosen = [p for p in picks_doc.get("picks", [])
              if p.get("setup") == "momentum" and p.get("grade") in swing.USABLE_GRADES and p.get("qty", 0) > 0]
    positions = [{"symbol": p["symbol"], "name": p["name"], "momentum_place": p.get("momentum_place"),
                  "planned_qty": p["qty"], "close_at_signal": p["close"], "max_entry": p.get("max_entry"),
                  "stop": p["stop"], "actual_entry": None, "actual_qty": None} for p in chosen[:top]]
    return {"signal_date": picks_doc["signal_date"], "buy_date": picks_doc["momentum_buy_date"],
            "sell_date": picks_doc["momentum_sell_date"], "monitor_until": until or picks_doc["momentum_sell_date"],
            "budget_inr": picks_doc.get("budget_inr"), "basket": picks_doc.get("basket"), "evidence": picks_doc.get("setups", {}).get("momentum", {}),
            "positions": positions}


# ---------------------------------------------------------------- assessment

def trading_days_between(start, end):
    """Trading days after `start` up to and including `end` (ISO dates)."""
    day = datetime.date.fromisoformat(start)
    last = datetime.date.fromisoformat(end)
    count = 0
    while day < last:
        day += datetime.timedelta(days=1)
        if is_trading_day(day):
            count += 1
    return count


def _change_pct(new, old):
    return (new / old - 1.0) * 100.0 if old else None


def assess(position, bars, nifty_bars, watch, today, rank=None):
    """Everything the report says about one stock. `bars` are daily bars, oldest first;
    during the session the last bar is today's bar so far."""
    out = {"symbol": position["symbol"], "name": position.get("name", position["symbol"]),
           "stop": position["stop"], "max_entry": position.get("max_entry"),
           "momentum_place": position.get("momentum_place"), "rank_now": rank}
    qty = position.get("actual_qty")
    qty = position.get("planned_qty", 0) if qty is None else qty
    out["qty"], out["real_fill"] = qty, position.get("actual_entry") is not None
    if not bars:
        out.update({"decision": "CHECK", "severity": "warn", "reason": "No price data could be read for this stock."})
        return out

    last_bar = bars[-1]
    last = last_bar["close"]
    prev_close = bars[-2]["close"] if len(bars) > 1 else None
    closes = [b["close"] for b in bars]
    sma20 = swing.sma(closes, 20)[-1] if len(closes) >= 20 else None
    sma50 = swing.sma(closes, 50)[-1] if len(closes) >= 50 else None
    out.update({"last": last, "price_date": last_bar["date"], "today_pct": _change_pct(last, prev_close),
                "day_high": last_bar["high"], "day_low": last_bar["low"],
                "above_sma20": bool(sma20 and last > sma20), "above_sma50": bool(sma50 and last > sma50),
                "sma20": sma20, "sma50": sma50,
                "five_day_pct": _change_pct(last, closes[-6]) if len(closes) > 5 else None,
                "to_stop_pct": _change_pct(last, position["stop"])})

    held = [b for b in bars if b["date"] >= watch["buy_date"]]
    nifty_held = [b for b in nifty_bars if b["date"] >= watch["buy_date"]]
    out["day_number"] = len(held)
    out["days_left"] = trading_days_between(today, watch["sell_date"]) if today <= watch["sell_date"] else 0

    if qty == 0:
        out.update({"decision": "SKIPPED", "severity": "info",
                    "reason": "You recorded this one as not bought; shown for reference only."})
        return out
    if not held:
        out.update({"decision": "WAIT", "severity": "info",
                    "reason": "The plan buys on %s%s." % (watch["buy_date"], (
                        ". Buy only if it trades below ₹%s" % format(position["max_entry"], ",.2f"))
                        if position.get("max_entry") else ", at the open")})
        return out

    buy_open = held[0]["open"]
    entry = position.get("actual_entry") or buy_open
    out.update({"entry": entry, "buy_open": buy_open,
                "since_entry_pct": _change_pct(last, entry), "pnl_inr": (last - entry) * qty,
                "invested_inr": entry * qty,
                "low_since": min(b["low"] for b in held), "high_since": max(b["high"] for b in held)})
    if nifty_held:
        out["nifty_since_pct"] = _change_pct(nifty_bars[-1]["close"], nifty_held[0]["open"])
        if out["nifty_since_pct"] is not None:
            out["vs_nifty_pct"] = out["since_entry_pct"] - out["nifty_since_pct"]

    stop_day = next((b["date"] for b in held if b["low"] <= position["stop"]), None)
    # Watch lists made before the buy limit was dropped still carry one; newer ones do not.
    opened_above = bool(position.get("max_entry")) and not out["real_fill"] and buy_open > position["max_entry"]
    out["plan_days"] = trading_days_between(watch["buy_date"], watch["sell_date"]) + 1
    basket = watch.get("basket") or swing.MOMENTUM["top_n"]
    out["basket"] = basket
    if stop_day:
        out.update({"decision": "EXIT", "severity": "act",
                    "reason": "Traded at or below the emergency stop ₹%s on %s. Sell if you still hold it." % (
                        format(position["stop"], ",.2f"), stop_day)})
    elif today >= watch["sell_date"]:
        out.update({"decision": "SELL TODAY", "severity": "act",
                    "reason": "Planned exit day. Sell at today's close, then re-run the screen for the next basket."})
    elif opened_above and len(held) == 1:
        out.update({"decision": "DO NOT CHASE", "severity": "act",
                    "reason": "Opened at ₹%s, above the buy limit ₹%s. Buy only if it comes back below the limit." % (
                        format(buy_open, ",.2f"), format(position["max_entry"], ",.2f"))})
    elif out["to_stop_pct"] is not None and out["to_stop_pct"] <= NEAR_STOP_PCT:
        out.update({"decision": "WATCH", "severity": "warn",
                    "reason": "Only %.1f%% above the emergency stop ₹%s." % (
                        out["to_stop_pct"], format(position["stop"], ",.2f"))})
    elif out["days_left"] == 1:
        out.update({"decision": "EXIT TOMORROW", "severity": "warn",
                    "reason": "Tomorrow (%s) is the planned exit day: sell at the close." % watch["sell_date"]})
    elif rank is not None and rank > basket:
        out.update({"decision": "HOLD, DO NOT RENEW", "severity": "info",
                    "reason": "It has slipped to #%d in the momentum ranking. Hold to the exit day, then let it go." % rank})
    else:
        out.update({"decision": "HOLD", "severity": "ok", "reason": "Inside the plan. No action needed."})
    return out


def summarize(rows, nifty_bars, watch):
    live = [r for r in rows if "pnl_inr" in r]
    invested = sum(r["invested_inr"] for r in live)
    pnl = sum(r["pnl_inr"] for r in live)
    nifty_held = [b for b in nifty_bars if b["date"] >= watch["buy_date"]]
    nifty_since = _change_pct(nifty_bars[-1]["close"], nifty_held[0]["open"]) if nifty_held else None
    nifty_today = _change_pct(nifty_bars[-1]["close"], nifty_bars[-2]["close"]) if len(nifty_bars) > 1 else None
    return {"positions": len(live), "invested_inr": invested, "pnl_inr": pnl,
            "pnl_pct": pnl / invested * 100.0 if invested else None,
            "nifty_since_pct": nifty_since, "nifty_today_pct": nifty_today,
            "nifty_last": nifty_bars[-1]["close"] if nifty_bars else None,
            "winners": sum(1 for r in live if r["pnl_inr"] > 0), "losers": sum(1 for r in live if r["pnl_inr"] < 0),
            "decisions": [r for r in rows if r.get("severity") in ("act", "warn")],
            "loss_at_stops_inr": sum((r["entry"] - r["stop"]) * r["qty"] for r in live)}


# ---------------------------------------------------------------- report

COLORS = {"act": ("#b42318", "#fef3f2"), "warn": ("#b54708", "#fffaeb"), "ok": ("#067647", "#ecfdf3"),
          "info": ("#344054", "#f2f4f7")}


def _pct(value, digits=2):
    return "n/a" if value is None else "%+.*f%%" % (digits, value)


def _inr(value, sign=False):
    if value is None:
        return "n/a"
    text = "₹{:,.0f}".format(abs(value))
    if sign:
        return ("+" if value >= 0 else "−") + text
    return text


def _tone(value):
    if value is None or abs(value) < 0.005:
        return "#344054"
    return "#067647" if value > 0 else "#b42318"


def _badge(row):
    fg, bg = COLORS[row.get("severity", "info")]
    return ('<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;'
            'font-weight:bold;color:%s;background:%s;white-space:nowrap">%s</span>' % (
                fg, bg, html.escape(row.get("decision", ""))))


def subject_line(summary, now):
    acts = sum(1 for r in summary["decisions"] if r["severity"] == "act")
    head = "%d action%s needed" % (acts, "" if acts == 1 else "s") if acts else "no action needed"
    tail = ""
    if summary["pnl_pct"] is not None:
        tail = " | basket %s, Nifty %s" % (_pct(summary["pnl_pct"]), _pct(summary["nifty_since_pct"]))
    return "Swing monitor %s: %s%s" % (now.strftime("%d %b %H:%M"), head, tail)


def render_html(rows, summary, watch, now, market_note, rank_date):
    e = html.escape
    cell = 'style="padding:8px 10px;border-bottom:1px solid #eaecf0;text-align:right;font-size:14px"'
    left = 'style="padding:8px 10px;border-bottom:1px solid #eaecf0;text-align:left;font-size:14px"'
    head = ('style="padding:8px 10px;border-bottom:2px solid #d0d5dd;text-align:right;font-size:12px;'
            'color:#475467;text-transform:uppercase"')
    head_left = head.replace("text-align:right", "text-align:left")
    parts = ['<div style="font-family:Segoe UI,Arial,sans-serif;color:#101828;max-width:760px;margin:0 auto">']
    parts.append('<h2 style="margin:0 0 4px 0">Swing basket monitor</h2>')
    parts.append('<div style="color:#475467;font-size:13px;margin-bottom:14px">%s IST · %s</div>' % (
        now.strftime("%A %d %b %Y, %H:%M"), e(market_note)))

    # decisions first
    decisions = summary["decisions"]
    if decisions:
        parts.append('<h3 style="margin:14px 0 6px 0">Decisions for you</h3>')
        for r in decisions:
            fg, bg = COLORS[r["severity"]]
            parts.append('<div style="border-left:4px solid %s;background:%s;padding:8px 12px;margin:6px 0;'
                         'font-size:14px"><b>%s</b> &nbsp;%s<br>%s</div>' % (
                             fg, bg, e(r["symbol"]), _badge(r), e(r["reason"])))
    else:
        fg, bg = COLORS["ok"]
        parts.append('<div style="border-left:4px solid %s;background:%s;padding:8px 12px;margin:10px 0;'
                     'font-size:14px"><b>No decision needed right now.</b> Every stock is inside the plan.</div>' % (fg, bg))

    # basket summary
    parts.append('<h3 style="margin:18px 0 6px 0">Basket so far</h3>')
    if summary["positions"]:
        beat = None
        if summary["pnl_pct"] is not None and summary["nifty_since_pct"] is not None:
            beat = summary["pnl_pct"] - summary["nifty_since_pct"]
        parts.append('<table style="border-collapse:collapse;font-size:14px"><tr>')
        for label, value, tone in (
                ("Profit / loss", "%s (%s)" % (_inr(summary["pnl_inr"], True), _pct(summary["pnl_pct"])), _tone(summary["pnl_inr"])),
                ("Nifty, same days", _pct(summary["nifty_since_pct"]), _tone(summary["nifty_since_pct"])),
                ("Basket vs Nifty", _pct(beat), _tone(beat)),
                ("Invested", _inr(summary["invested_inr"]), "#101828"),
                ("Up / down", "%d / %d" % (summary["winners"], summary["losers"]), "#101828")):
            parts.append('<td style="padding:6px 18px 6px 0"><div style="font-size:12px;color:#475467">%s</div>'
                         '<div style="font-size:17px;font-weight:bold;color:%s">%s</div></td>' % (label, tone, value))
        parts.append("</tr></table>")
        parts.append('<div style="font-size:13px;color:#475467;margin-top:4px">Plan: buy date %s, sell at the close on %s. '
                     'Loss if every emergency stop were hit: %s.</div>' % (
                         watch["buy_date"], watch["sell_date"], _inr(summary["loss_at_stops_inr"])))
    else:
        parts.append('<div style="font-size:14px">Nothing is bought yet under the plan (buy date %s).</div>' % watch["buy_date"])

    # per-stock table
    parts.append('<h3 style="margin:18px 0 6px 0">Each stock</h3>')
    parts.append('<table style="border-collapse:collapse;width:100%">')
    parts.append("<tr><th %s>Stock</th><th %s>Last</th><th %s>Today</th><th %s>Since buy</th><th %s>P/L</th>"
                 "<th %s>vs Nifty</th><th %s>Above stop</th><th %s>Decision</th></tr>" % (
                     head_left, head, head, head, head, head, head, head_left))
    for r in rows:
        if "last" not in r:
            parts.append('<tr><td %s><b>%s</b></td><td %s colspan="6">no price data</td><td %s>%s</td></tr>' % (
                left, e(r["symbol"]), cell, left, _badge(r)))
            continue
        parts.append(
            "<tr><td %s><b>%s</b><br><span style=\"font-size:12px;color:#475467\">%s shares%s</span></td>"
            "<td %s>₹%s</td><td %s><span style=\"color:%s\">%s</span></td>"
            "<td %s><span style=\"color:%s\">%s</span></td><td %s><span style=\"color:%s\">%s</span></td>"
            "<td %s><span style=\"color:%s\">%s</span></td><td %s>%s</td><td %s>%s</td></tr>" % (
                left, e(r["symbol"]), r["qty"], "" if r.get("real_fill") else ", planned",
                cell, format(r["last"], ",.2f"),
                cell, _tone(r.get("today_pct")), _pct(r.get("today_pct")),
                cell, _tone(r.get("since_entry_pct")), _pct(r.get("since_entry_pct")),
                cell, _tone(r.get("pnl_inr")), _inr(r.get("pnl_inr"), True),
                cell, _tone(r.get("vs_nifty_pct")), _pct(r.get("vs_nifty_pct")),
                cell, _pct(r.get("to_stop_pct"), 1), left, _badge(r)))
    parts.append("</table>")

    # health detail
    parts.append('<h3 style="margin:18px 0 6px 0">Progress and health</h3>')
    for r in rows:
        if "last" not in r:
            continue
        lines = []
        if "entry" in r:
            lines.append("Day %d of %d · %d trading day%s to the exit · bought at ₹%s (%s), range since ₹%s to ₹%s" % (
                r["day_number"], r["plan_days"], r["days_left"], "" if r["days_left"] == 1 else "s",
                format(r["entry"], ",.2f"), "your fill" if r.get("real_fill") else "buy-day open, assumed",
                format(r["low_since"], ",.2f"), format(r["high_since"], ",.2f")))
        trend = "%s its 20-day average, %s its 50-day average" % (
            "above" if r["above_sma20"] else "below", "above" if r["above_sma50"] else "below")
        lines.append("Trend: %s · last 5 days %s · today's range ₹%s to ₹%s" % (
            trend, _pct(r.get("five_day_pct")), format(r["day_low"], ",.2f"), format(r["day_high"], ",.2f")))
        rank_text = "Momentum rank when picked: #%s" % r.get("momentum_place")
        if r.get("rank_now") is not None:
            rank_text += " · now #%d (%s, as of %s)" % (
                r["rank_now"], ("still in the top %d" if r["rank_now"] <= r.get("basket", 20) else "out of the top %d")
                % r.get("basket", 20), rank_date)
        rank_text += " · emergency stop ₹%s" % format(r["stop"], ",.2f")
        if r.get("max_entry"):
            rank_text += " · buy limit was ₹%s" % format(r["max_entry"], ",.2f")
        lines.append(rank_text)
        parts.append('<div style="margin:8px 0;padding:8px 12px;border:1px solid #eaecf0;border-radius:6px;font-size:13px">'
                     '<b style="font-size:14px">%s</b> <span style="color:#475467">%s</span> &nbsp;%s<br>%s<br>'
                     '<span style="color:#475467">%s</span></div>' % (
                         e(r["symbol"]), e(r["name"]), _badge(r), e(r["reason"]), "<br>".join(e(x) for x in lines)))

    evidence = watch.get("evidence") or {}
    note = ""
    if evidence.get("avg_net_pct") is not None:
        note = ("The rule behind this basket averaged %s per %d trading days after costs in testing (%s better than "
                "holding every stock), and about half of single trades lost. " % (
                    _pct(evidence["avg_net_pct"]), evidence.get("avg_days_held") or 10,
                    _pct(evidence.get("edge_over_holding_pct"))))
    parts.append('<div style="margin-top:18px;padding-top:10px;border-top:1px solid #eaecf0;font-size:12px;color:#475467">'
                 '%sOne week of results says very little either way. Prices are from Yahoo Finance and can lag the '
                 'exchange; profit and loss assumes the planned quantity at the buy-day open unless you recorded your '
                 'fills in trader/swing_watch.json. This report places no orders and is not financial advice.</div>' % e(note))
    parts.append("</div>")
    return "\n".join(parts)


def render_text(rows, summary, watch, now):
    lines = ["Swing basket monitor, %s IST" % now.strftime("%d %b %Y %H:%M"), ""]
    if summary["decisions"]:
        lines.append("DECISIONS FOR YOU")
        lines.extend("  %s: %s. %s" % (r["symbol"], r["decision"], r["reason"]) for r in summary["decisions"])
    else:
        lines.append("No decision needed right now.")
    lines.append("")
    if summary["positions"]:
        lines.append("Basket: %s (%s) | Nifty same days %s | invested %s" % (
            _inr(summary["pnl_inr"], True), _pct(summary["pnl_pct"]), _pct(summary["nifty_since_pct"]),
            _inr(summary["invested_inr"])))
    for r in rows:
        if "last" in r:
            lines.append("  %-12s last %10s  today %8s  since buy %8s  above stop %7s  %s" % (
                r["symbol"], format(r["last"], ",.2f"), _pct(r.get("today_pct")), _pct(r.get("since_entry_pct")),
                _pct(r.get("to_stop_pct"), 1), r["decision"]))
    lines += ["", "Plan: buy date %s, sell at the close on %s." % (watch["buy_date"], watch["sell_date"]),
              "Not financial advice. Nothing was ordered."]
    return "\n".join(lines)


# ---------------------------------------------------------------- email

def email_settings():
    settings = _read_json(SETTINGS_PATH, {}) or {}

    def pick(env, key, default=None):
        return os.environ.get(env) or settings.get(key) or default

    return {"to": pick("EMAIL_TO", "email_to"), "user": pick("SMTP_USER", "smtp_user"),
            "password": pick("SMTP_PASSWORD", "smtp_password"),
            "host": pick("SMTP_HOST", "smtp_host", "smtp.gmail.com"),
            "port": int(pick("SMTP_PORT", "smtp_port", 587))}


def send_email(subject, text_body, html_body, cfg=None, smtp_class=smtplib.SMTP):
    cfg = cfg or email_settings()
    missing = [k for k in ("to", "user", "password") if not cfg.get(k)]
    if missing:
        raise RuntimeError("email is not set up: add %s to settings.json" % ", ".join(
            {"to": "email_to", "user": "smtp_user", "password": "smtp_password"}[k] for k in missing))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["user"], cfg["to"]
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtp_class(cfg["host"], cfg["port"], timeout=30) as server:
        server.starttls()
        server.login(cfg["user"], str(cfg["password"]).replace(" ", ""))
        server.send_message(msg)


# ---------------------------------------------------------------- commands

def refresh_rank(today):
    """Where every stock stands in the momentum ranking after today's close (slow: full download)."""
    universe, data, _ = swing.load_market(force=True, quiet=True)
    prepared = swing._prepared(data, universe)
    latest = max(p["bars"][-1]["date"] for p in prepared.values())
    ranks = {symbol: place for place, (_, symbol, _) in enumerate(swing.momentum_ranking(prepared, latest), 1)}
    doc = {"date": latest, "refreshed": today, "ranks": ranks}
    _write_json(RANK_PATH, doc)
    return doc


def cmd_init(args):
    picks = _read_json(PICKS_PATH)
    if not picks:
        print("No picks found. Run `python trader-scanner/swing_indian.py picks` first.", file=sys.stderr)
        return 1
    if os.path.isfile(WATCH_PATH) and not args.force:
        print("A watch list already exists at %s. Use --force to replace it." % WATCH_PATH, file=sys.stderr)
        return 1
    watch = build_watch(picks, args.top, args.until)
    if not watch["positions"]:
        print("The latest picks have no usable momentum candidates; nothing to watch.", file=sys.stderr)
        return 1
    _write_json(WATCH_PATH, watch)
    print("Watching %s from %s; planned exit %s; monitoring until %s." % (
        ", ".join(p["symbol"] for p in watch["positions"]), watch["buy_date"], watch["sell_date"], watch["monitor_until"]))
    return 0


def cmd_run(args):
    now = to_ist()
    today = now.date().isoformat()
    watch = _read_json(WATCH_PATH)
    if not watch:
        print("No watch list. Run `python trader-alerts/swing_monitor.py init` first.", file=sys.stderr)
        return 1
    if not args.force:
        if not is_trading_day(now.date()):
            print("Not a trading day (%s). Nothing sent." % (holiday_name(now.date()) or "weekend"))
            return 0
        if today > watch.get("monitor_until", watch["sell_date"]):
            print("Monitoring ended on %s. Nothing sent." % watch.get("monitor_until", watch["sell_date"]))
            return 0

    rank_doc = _read_json(RANK_PATH, {}) or {}
    if args.rank or (now.strftime("%H:%M") >= RANK_AFTER and rank_doc.get("refreshed") != today and not args.no_rank):
        try:
            rank_doc = refresh_rank(today)
        except Exception as exc:
            print("Could not refresh the momentum ranking: %s" % exc, file=sys.stderr)
    ranks = rank_doc.get("ranks", {})

    def daily(symbol):
        try:
            return swing._yahoo_daily(symbol)
        except Exception as exc:
            print("No prices for %s: %s" % (symbol, exc), file=sys.stderr)
            return []

    nifty_bars = daily("^NSEI")
    if not nifty_bars:
        print("Could not read Nifty prices; no report built.", file=sys.stderr)
        return 1
    rows = [assess(p, daily(p["symbol"] + ".NS"), nifty_bars, watch, today, ranks.get(p["symbol"]))
            for p in watch["positions"]]
    summary = summarize(rows, nifty_bars, watch)
    regime = swing.market_regime(nifty_bars)
    market_note = "%s (Nifty %s, %s today)" % (regime["note"], format(summary["nifty_last"], ",.2f"),
                                               _pct(summary["nifty_today_pct"]))
    subject = subject_line(summary, now)
    page = render_html(rows, summary, watch, now, market_note, rank_doc.get("date"))
    text = render_text(rows, summary, watch, now)

    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "swing-%s.html" % now.strftime("%Y-%m-%d-%H%M"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<!doctype html><meta charset=\"utf-8\"><title>%s</title>%s" % (html.escape(subject), page))
    print(text)
    print("\nSaved: %s" % path)
    if args.no_email:
        return 0
    try:
        send_email(subject, text, page)
    except Exception as exc:
        print("Email NOT sent: %s" % exc, file=sys.stderr)
        return 2
    print("Emailed: %s" % subject)
    return 0


def cmd_test_email(_args):
    now = to_ist()
    try:
        send_email("Swing monitor test, %s" % now.strftime("%d %b %H:%M"),
                   "Email delivery from the swing monitor works.",
                   "<p>Email delivery from the swing monitor works.</p>")
    except Exception as exc:
        print("Email NOT sent: %s" % exc, file=sys.stderr)
        return 2
    print("Test email sent.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Monitor the swing basket and email a report")
    sub = parser.add_subparsers(dest="command")
    init = sub.add_parser("init", help="start watching the top picks from the latest screen")
    init.add_argument("--top", type=int, default=5)
    init.add_argument("--until", help="last day to send reports (YYYY-MM-DD); default is the planned exit day")
    init.add_argument("--force", action="store_true", help="replace an existing watch list")
    run = sub.add_parser("run", help="build, save and email the report")
    run.add_argument("--no-email", action="store_true")
    run.add_argument("--rank", action="store_true", help="refresh the momentum ranking now (slow)")
    run.add_argument("--no-rank", action="store_true", help="never refresh the momentum ranking in this run")
    run.add_argument("--force", action="store_true", help="run even on a non-trading day or after the end date")
    sub.add_parser("test-email", help="send a one-line test email")
    args = parser.parse_args(argv)
    handler = {"init": cmd_init, "run": cmd_run, "test-email": cmd_test_email}.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
