#!/usr/bin/env python3
"""Local Zerodha Kite Connect adapter with explicit live-order gates."""

import argparse
import datetime
import getpass
import hashlib
import json
import math
import os
import re
import sys

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "trader-risk")))
from check_indian import check_order_risk


SESSION_PATH = os.path.join("trader", "state", "kite_session.json")
STATE_PATH = os.path.join("trader", "state", "kite_broker.json")
ORDER_PATH = os.path.join("trader", "orders.json")
CONFIG_PATH = "config_indian.json"
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "settings.json")


class KiteError(Exception):
    pass


def _read_json(path, required=True):
    if not os.path.isfile(path):
        if required:
            raise KiteError("file not found: %s" % path)
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise KiteError("cannot read %s: %s" % (path, exc))


def _write_json(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(temp, path)
    except OSError as exc:
        raise KiteError("cannot write %s: %s" % (path, exc))


def _now_ist():
    utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return utc + datetime.timedelta(hours=5, minutes=30)


def _today():
    return _now_ist().date().isoformat()


def _positive_float(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise KiteError("%s must be a positive number" % label)
    if not math.isfinite(number) or number <= 0:
        raise KiteError("%s must be a positive number" % label)
    return number


def _kite_credentials():
    settings = _read_json(SETTINGS_PATH, required=False) or {}
    api_key = os.environ.get("KITE_API_KEY") or settings.get("kite_api_key")
    api_secret = os.environ.get("KITE_API_SECRET") or settings.get("kite_api_secret")
    return api_key, api_secret


def _load_kite(session_path=SESSION_PATH, kite_class=None):
    session = _read_json(session_path, required=False) or {}
    env_token = os.environ.get("KITE_ACCESS_TOKEN")
    if env_token:
        api_key, access_token = _kite_credentials()[0] or session.get("api_key"), env_token
    else:
        # A token only works with the API key it was issued for, so use the key
        # the login saved next to it rather than whatever this shell has set.
        api_key = session.get("api_key") or _kite_credentials()[0]
        access_token = session.get("access_token")
    if not api_key or not access_token:
        raise KiteError("run `python trader-broker/kite.py login` first")
    if kite_class is None:
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            raise KiteError("kiteconnect is missing; install requirements.txt")
        kite_class = KiteConnect
    kite = kite_class(api_key=api_key)
    kite.set_access_token(access_token)
    return kite


def _order_from_file(path):
    doc = _read_json(path)
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or len(orders) != 1 or not isinstance(orders[0], dict):
        raise KiteError("Kite needs exactly one order object in %s" % path)
    order = orders[0]
    required = ("symbol", "exchange", "side", "qty", "type", "product", "validity", "plan")
    missing = [key for key in required if order.get(key) is None]
    if missing:
        raise KiteError("order is missing Kite fields: %s" % ", ".join(missing))
    if (order.get("order_class") or order.get("take_profit_limit_price") is not None
            or order.get("stop_loss_limit_price") is not None):
        raise KiteError("Kite does not support this project's attached bracket/OCO order; no order was sent")
    if order.get("stop_loss_stop_price") is not None:
        raise KiteError("Kite stop orders are separate; remove the bracket leg and manage exits separately")

    symbol = str(order["symbol"]).strip().upper()
    exchange = str(order["exchange"]).strip().upper()
    side = str(order["side"]).strip().lower()
    order_type = str(order["type"]).strip().upper()
    product = str(order["product"]).strip().upper()
    validity = str(order["validity"]).strip().upper()
    qty_float = _positive_float(order["qty"], "qty")
    if not symbol or not re.match(r"^[A-Z0-9&._-]+$", symbol):
        raise KiteError("symbol must be a single NSE/BSE trading symbol")
    if exchange not in ("NSE", "BSE"):
        raise KiteError("this adapter currently supports NSE and BSE equities only")
    if side not in ("buy", "sell"):
        raise KiteError("side must be buy or sell")
    if qty_float != int(qty_float):
        raise KiteError("qty must be a positive whole number")
    if order_type != "LIMIT":
        raise KiteError("only LIMIT orders are enabled so the entry price cannot exceed the checked price")
    if product != "CNC":
        raise KiteError("only CNC equity orders are enabled; MIS/NRML can add leverage or expiry risk")
    if validity != "DAY":
        raise KiteError("only DAY validity is enabled")
    _positive_float(order.get("limit_price"), "limit_price")
    plan = order.get("plan")
    if not isinstance(plan, dict):
        raise KiteError("plan must contain entry and stop prices for the risk check")
    for key in ("entry", "stop"):
        _positive_float(plan.get(key), "plan.%s" % key)
    if side == "buy" and float(plan["stop"]) >= float(plan["entry"]):
        raise KiteError("a long order's stop must be below its planned entry")
    if side == "sell":
        raise KiteError("sell-to-close is available from the Kite app; automated sell sizing is not enabled")
    normalized = dict(order)
    normalized.update({
        "symbol": symbol, "exchange": exchange, "side": side, "qty": int(qty_float),
        "type": order_type, "product": product, "validity": validity,
    })
    return normalized


def fingerprint(order):
    fields = ("symbol", "exchange", "side", "qty", "type", "product", "validity",
              "limit_price", "plan")
    core = {key: order[key] for key in fields if key in order and order[key] is not None}
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _daily_state(path=STATE_PATH):
    return _read_json(path, required=False) or {"checks": [], "orders": []}


def _orders_today(state, today):
    return [rec for rec in state.get("orders", [])
            if rec.get("date") == today and rec.get("status") in ("placed", "filled")]


def _max_loss(order):
    plan = order["plan"]
    entry = max(float(plan["entry"]), float(order["limit_price"]))
    return round(int(order["qty"]) * abs(entry - float(plan["stop"])), 2)


def _risk_result(order, state, today):
    active = _orders_today(state, today)
    used_risk = sum(float(rec.get("max_loss") or 0) for rec in active)
    config = _read_json(CONFIG_PATH, required=False) or {}
    # Every order this adapter sends is a delivery (CNC) buy, so the swing day limits apply.
    max_daily = float(config.get("swing_max_daily_loss_inr", config.get("max_daily_loss_inr", 0)) or 0)
    new_risk = _max_loss(order)
    order_value = int(order["qty"]) * float(order["limit_price"])
    budget = float(config.get("budget_inr", 0) or 0)
    max_order = float(config.get("max_order_value_inr", budget) or 0)
    if max_order and order_value > max_order:
        return {"status": "BLOCK", "reasons": [
            "ORDER_VALUE_LIMIT: order value INR %.2f exceeds the configured limit INR %.2f"
            % (order_value, max_order)]}
    if max_daily and used_risk + new_risk > max_daily:
        return {"status": "BLOCK", "reasons": [
            "DAILY_RISK_LIMIT: today's recorded and proposed max loss exceeds the daily limit"]}
    result = check_order_risk(
        symbol=order["symbol"], qty=order["qty"], entry=max(
            float(order["plan"]["entry"]), float(order["limit_price"])),
        stop=float(order["plan"]["stop"]), realized_loss_today=used_risk, trades_today=len(active),
        swing=True)
    return result


def cmd_login(args):
    api_key, api_secret = _kite_credentials()
    if not api_key or not api_secret:
        raise KiteError("set kite_api_key and kite_api_secret in settings.json or KITE_API_KEY and "
                        "KITE_API_SECRET in your local environment")
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        raise KiteError("kiteconnect is missing; install requirements.txt")
    kite = KiteConnect(api_key=api_key)
    print("Open this Zerodha login URL in your browser:\n%s" % kite.login_url())
    request_token = getpass.getpass("Paste the returned request_token here (input hidden): ").strip()
    if not request_token:
        raise KiteError("request_token cannot be empty")
    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session.get("access_token")
    if not access_token:
        raise KiteError("Kite did not return an access token")
    _write_json(args.session, {"api_key": api_key, "access_token": access_token})
    print("Kite session saved locally. Access token is not displayed.")
    print("The token expires daily; run this login again when Kite rejects it.")
    return 0


def cmd_profile(args):
    kite = _load_kite(args.session)
    profile = kite.profile()
    safe = {key: profile.get(key) for key in ("user_id", "user_name", "broker", "exchanges", "products")}
    print(json.dumps(safe, indent=2))
    return 0


def cmd_quote(args):
    kite = _load_kite(args.session)
    instrument = "%s:%s" % (args.exchange, args.symbol.upper())
    quote = kite.ltp(instrument)
    if instrument not in quote:
        raise KiteError("Kite returned no quote for %s" % instrument)
    print(json.dumps({"instrument": instrument, "last_price": quote[instrument]["last_price"]}, indent=2))
    return 0


def cmd_orders(args):
    kite = _load_kite(args.session)
    rows = kite.orders()
    print(json.dumps(rows, indent=2))
    return 0


def cmd_holdings(args):
    kite = _load_kite(args.session)
    print(json.dumps(kite.holdings(), indent=2))
    return 0


def cmd_positions(args):
    kite = _load_kite(args.session)
    print(json.dumps(kite.positions(), indent=2))
    return 0


def cmd_check(args):
    order = _order_from_file(args.order)
    state = _daily_state(args.state)
    today = _today()
    uncertain = [rec for rec in state.get("orders", [])
                 if rec.get("date") == today and rec.get("status") == "uncertain"]
    if uncertain:
        raise KiteError("a prior Kite request has an unknown outcome; verify it in Kite and do not retry today")
    kite = _load_kite(args.session)
    untracked = _untracked_orders(kite.orders(), state, today)
    if untracked:
        raise KiteError("Kite has untracked orders today; reconcile them before running a new risk check")
    result = _risk_result(order, state, today)
    fp = fingerprint(order)
    record = {"date": today, "at": _now_ist().isoformat(), "fingerprint": fp,
              "status": result.get("status"), "result": result, "max_loss": _max_loss(order)}
    state.setdefault("checks", []).append(record)
    _write_json(args.state, state)
    print("Kite order %s: %s" % (fp, result.get("status", "BLOCK")))
    print("  %s %d %s on %s, LIMIT INR %s, CNC, DAY" % (
        order["side"].upper(), order["qty"], order["symbol"], order["exchange"], order["limit_price"]))
    print("  Planned entry INR %s, stop INR %s (stop is not sent to Kite)." % (
        order["plan"]["entry"], order["plan"]["stop"]))
    print("Max planned loss: INR %.2f." % record["max_loss"])
    for reason in result.get("reasons", []):
        print("  " + str(reason))
    if result.get("status") == "PASS":
        print("Next: approve this exact order after reviewing its ticket.")
        return 0
    return 1


def cmd_approve(args):
    if args.reply.strip().lower() not in ("yes", "yes place it"):
        print("Not recorded: approval requires an explicit yes for this one order.")
        return 1
    order = _order_from_file(args.order)
    state = _daily_state(args.state)
    today = _today()
    fp = fingerprint(order)
    checks = [rec for rec in state.get("checks", [])
              if rec.get("date") == today and rec.get("fingerprint") == fp]
    if not checks or checks[-1].get("status") != "PASS":
        raise KiteError("this exact order has no passing Indian risk check today; run check first")
    previous = [rec for rec in state.get("orders", [])
                if rec.get("date") == today and rec.get("fingerprint") == fp]
    if previous and previous[-1].get("status") in ("approved", "placed", "filled"):
        raise KiteError("this order already has an approval or placement record")
    if previous and checks[-1].get("at", "") <= previous[-1].get("at", ""):
        raise KiteError("run a new risk check after the previous attempt before approving again")
    state.setdefault("orders", []).append({
        "date": today, "at": _now_ist().isoformat(), "fingerprint": fp,
        "symbol": order["symbol"], "side": order["side"],
        "qty": order["qty"], "max_loss": _max_loss(order), "status": "approved",
        "reply": args.reply,
    })
    _write_json(args.state, state)
    print("Recorded yes for %s %s %s. No order has been sent." % (
        order["side"].upper(), order["qty"], order["symbol"]))
    print("The live placement command requires a separate interactive confirmation.")
    return 0


def _kite_order(order):
    payload = {
        "variety": "regular",
        "exchange": order["exchange"],
        "tradingsymbol": order["symbol"],
        "transaction_type": "BUY",
        "quantity": order["qty"],
        "product": order["product"],
        "order_type": order["type"],
        "validity": order["validity"],
    }
    if order["type"] == "LIMIT":
        payload["price"] = float(order["limit_price"])
    return payload


def cmd_place(args):
    order = _order_from_file(args.order)
    state = _daily_state(args.state)
    today = _today()
    fp = fingerprint(order)
    checks = [rec for rec in state.get("checks", [])
              if rec.get("date") == today and rec.get("fingerprint") == fp]
    approvals = [rec for rec in state.get("orders", [])
                 if rec.get("date") == today and rec.get("fingerprint") == fp]
    if not checks or checks[-1].get("status") != "PASS":
        raise KiteError("no passing risk check for this exact order today; nothing was sent")
    if not approvals or approvals[-1].get("status") != "approved":
        raise KiteError("no explicit yes recorded for this exact order; nothing was sent")
    if not sys.stdin.isatty():
        raise KiteError("live placement requires an interactive terminal; scheduled/background execution is disabled")

    print("LIVE ZERODHA ORDER - REAL MONEY")
    print("  %s %s %s on %s, %s %s, CNC, DAY" % (
        order["side"].upper(), order["qty"], order["symbol"], order["exchange"],
        order["type"], ("at INR %s" % order["limit_price"]) if order["type"] == "LIMIT" else ""))
    print("  The planned stop is NOT attached to this order. Manage the exit separately in Kite.")
    print("  Exact order fingerprint: %s" % fp)
    confirmation = input("Type PLACE LIVE %s to submit exactly this one order: " % fp).strip()
    if confirmation != "PLACE LIVE %s" % fp:
        print("Confirmation did not match. Nothing was sent.")
        return 1

    if _today() != today:
        raise KiteError("the Indian trading date changed during confirmation; run the risk check again")
    result = _risk_result(order, state, today)
    if result.get("status") != "PASS":
        raise KiteError("the final risk recheck blocked this order: %s" % "; ".join(result.get("reasons", [])))
    kite = _load_kite(args.session)
    if _untracked_orders(kite.orders(), state, today):
        raise KiteError("Kite has untracked orders today; nothing was sent")
    payload = _kite_order(order)
    try:
        from kiteconnect.exceptions import KiteException
    except ImportError:
        raise KiteError("kiteconnect is missing; install requirements.txt")
    try:
        order_id = kite.place_order(**payload)
    except (KiteException, requests.exceptions.RequestException) as exc:
        uncertain = isinstance(exc, requests.exceptions.RequestException)
        state.setdefault("orders", []).append({
            "date": today, "at": _now_ist().isoformat(), "fingerprint": fp,
            "symbol": order["symbol"], "side": order["side"],
            "qty": order["qty"], "max_loss": _max_loss(order),
            "status": "uncertain" if uncertain else "failed",
            "note": str(exc),
        })
        try:
            _write_json(args.state, state)
        except KiteError as log_error:
            raise KiteError("Kite request failed (%s), and its failure could not be logged (%s); "
                            "check Kite before any retry" % (exc, log_error))
        if uncertain:
            raise KiteError("Kite's response was lost; the order may have been accepted. Verify in Kite; "
                            "new checks are blocked for today: %s" % exc)
        raise KiteError("Kite rejected the request; do not retry without a new risk check and approval: %s" % exc)
    state.setdefault("orders", []).append({
        "date": today, "at": _now_ist().isoformat(), "fingerprint": fp,
        "symbol": order["symbol"], "side": order["side"],
        "qty": order["qty"], "max_loss": _max_loss(order), "status": "placed",
        "broker_order_id": order_id,
    })
    try:
        _write_json(args.state, state)
    except KiteError as exc:
        raise KiteError("Kite accepted order %s, but local logging failed (%s); verify its status in Kite "
                        "before taking any further action" % (order_id, exc))
    print("Kite accepted the order request (order id %s); this does not guarantee a fill." % order_id)
    return 0


def _untracked_orders(broker_orders, state, today):
    known = {str(rec.get("broker_order_id")) for rec in state.get("orders", [])
             if rec.get("date") == today and rec.get("broker_order_id")}
    active = []
    for order in broker_orders:
        status = str(order.get("status", "")).upper()
        try:
            filled = float(order.get("filled_quantity") or 0)
        except (TypeError, ValueError):
            filled = 0
        if status in ("CANCELLED", "REJECTED") and filled <= 0:
            continue
        if str(order.get("order_id")) not in known:
            active.append(order)
    return active


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Zerodha Kite Connect adapter")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="exchange a browser login request token")
    login.add_argument("--session", default=SESSION_PATH)

    for name, handler in (("profile", cmd_profile), ("orders", cmd_orders),
                          ("holdings", cmd_holdings), ("positions", cmd_positions)):
        p = sub.add_parser(name, help="read-only Kite account data")
        p.add_argument("--session", default=SESSION_PATH)
        p.set_defaults(handler=handler)

    quote = sub.add_parser("quote", help="read a last-traded price")
    quote.add_argument("--exchange", choices=("NSE", "BSE"), default="NSE")
    quote.add_argument("--symbol", required=True)
    quote.add_argument("--session", default=SESSION_PATH)
    quote.set_defaults(handler=cmd_quote)

    for name, handler in (("check", cmd_check), ("approve", cmd_approve), ("place", cmd_place)):
        p = sub.add_parser(name, help={"check": "risk check the exact order",
                                      "approve": "record an explicit yes",
                                      "place": "submit after a second local confirmation"}[name])
        p.add_argument("--order", default=ORDER_PATH)
        p.add_argument("--state", default=STATE_PATH)
        p.set_defaults(handler=handler)
        if name in ("check", "place"):
            p.add_argument("--session", default=SESSION_PATH)
        if name == "approve":
            p.add_argument("--reply", required=True)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    if args.command == "login":
        return cmd_login(args)
    try:
        return args.handler(args)
    except KiteError as exc:
        print("kite.py: %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:
        # kiteconnect's own errors (expired token, missing permission) are not KiteError
        if type(exc).__module__.startswith("kiteconnect"):
            hint = ""
            if type(exc).__name__ == "TokenException":
                hint = " Run `python trader-broker/kite.py login` in your own terminal."
            print("kite.py: Kite refused the request: %s.%s" % (exc, hint), file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
