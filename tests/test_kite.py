import json
import os
import tempfile
import unittest
from argparse import Namespace
from unittest import mock

from _load import load

kite = load("trader-broker", "kite")
cron_runner = load("telegram_bot", "cron_runner")


ORDER = {
    "symbol": "INFY",
    "exchange": "NSE",
    "side": "buy",
    "qty": "5",
    "type": "limit",
    "limit_price": "1500",
    "product": "CNC",
    "validity": "DAY",
    "plan": {"entry": 1500, "stop": 1450},
}


class KiteOrders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.order_path = os.path.join(self.temp.name, "orders.json")
        self.state_path = os.path.join(self.temp.name, "state.json")
        with open(self.order_path, "w", encoding="utf-8") as fh:
            json.dump({"orders": [ORDER]}, fh)

    def tearDown(self):
        self.temp.cleanup()

    def test_credentials_read_settings_with_environment_override(self):
        settings_path = os.path.join(self.temp.name, "settings.json")
        with open(settings_path, "w", encoding="utf-8") as fh:
            json.dump({"kite_api_key": "local-key", "kite_api_secret": "local-secret"}, fh)
        with mock.patch.object(kite, "SETTINGS_PATH", settings_path), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(kite._kite_credentials(), ("local-key", "local-secret"))
        with mock.patch.object(kite, "SETTINGS_PATH", settings_path), \
                mock.patch.dict(os.environ, {"KITE_API_KEY": "env-key"}, clear=True):
            self.assertEqual(kite._kite_credentials(), ("env-key", "local-secret"))

    def test_builds_kite_order_without_sending_the_planned_stop(self):
        order = kite._order_from_file(self.order_path)
        self.assertEqual(kite._kite_order(order), {
            "variety": "regular",
            "exchange": "NSE",
            "tradingsymbol": "INFY",
            "transaction_type": "BUY",
            "quantity": 5,
            "product": "CNC",
            "order_type": "LIMIT",
            "validity": "DAY",
            "price": 1500.0,
        })

    def test_fingerprint_covers_exchange_and_limit_price(self):
        order = kite._order_from_file(self.order_path)
        self.assertNotEqual(kite.fingerprint(order), kite.fingerprint(dict(order, exchange="BSE")))
        self.assertNotEqual(kite.fingerprint(order), kite.fingerprint(dict(order, limit_price="1510")))

    def test_rejects_attached_brackets_and_non_cnc_products(self):
        for update in ({"order_class": "bracket"}, {"product": "MIS"}):
            with open(self.order_path, "w", encoding="utf-8") as fh:
                json.dump({"orders": [dict(ORDER, **update)]}, fh)
            with self.assertRaises(kite.KiteError):
                kite._order_from_file(self.order_path)

    def test_rejects_market_and_nonfinite_prices(self):
        for update in ({"type": "market"}, {"limit_price": "NaN"}, {"qty": "Infinity"}):
            with open(self.order_path, "w", encoding="utf-8") as fh:
                json.dump({"orders": [dict(ORDER, **update)]}, fh)
            with self.assertRaises(kite.KiteError):
                kite._order_from_file(self.order_path)

    def test_untracked_fills_block_even_after_cancel(self):
        orders = [{"order_id": "abc", "status": "CANCELLED", "filled_quantity": 1},
                  {"order_id": "def", "status": "REJECTED", "filled_quantity": 0}]
        self.assertEqual(kite._untracked_orders(orders, {"orders": []}, "2026-11-12"), [orders[0]])

    def test_daily_risk_counts_previous_placed_risk_conservatively(self):
        config_path = os.path.join(self.temp.name, "config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump({"max_daily_loss_inr": 300, "budget_inr": 50000}, fh)
        order = kite._order_from_file(self.order_path)
        state = {"orders": [{"date": "2026-11-12", "status": "placed", "max_loss": 100}]}
        with mock.patch.object(kite, "CONFIG_PATH", config_path), \
                mock.patch.object(kite, "check_order_risk") as risk_check:
            result = kite._risk_result(order, state, "2026-11-12")
        self.assertEqual(result["status"], "BLOCK")
        risk_check.assert_not_called()

    @mock.patch.object(kite, "_today", return_value="2026-11-12")
    @mock.patch.object(kite, "_load_kite")
    @mock.patch.object(kite, "check_order_risk", return_value={"status": "PASS", "reasons": []})
    def test_check_persists_a_passing_verdict_for_the_exact_order(self, risk_check, load_kite, _today):
        config_path = os.path.join(self.temp.name, "config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump({"max_daily_loss_inr": 5000, "budget_inr": 50000}, fh)
        load_kite.return_value.orders.return_value = []
        args = Namespace(order=self.order_path, state=self.state_path, session="unused")
        with mock.patch.object(kite, "CONFIG_PATH", config_path):
            self.assertEqual(kite.cmd_check(args), 0)
        state = kite._daily_state(self.state_path)
        self.assertEqual(state["checks"][0]["fingerprint"],
                         kite.fingerprint(kite._order_from_file(self.order_path)))
        self.assertEqual(state["checks"][0]["status"], "PASS")
        risk_check.assert_called_once_with(symbol="INFY", qty=5, entry=1500.0, stop=1450.0,
                                           realized_loss_today=0, trades_today=0, swing=True)

    def test_delivery_orders_use_the_swing_day_limit_when_it_is_set(self):
        config_path = os.path.join(self.temp.name, "config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump({"max_daily_loss_inr": 300, "swing_max_daily_loss_inr": 10000, "budget_inr": 50000}, fh)
        order = kite._order_from_file(self.order_path)
        state = {"orders": [{"date": "2026-11-12", "status": "placed", "max_loss": 100}]}
        with mock.patch.object(kite, "CONFIG_PATH", config_path), \
                mock.patch.object(kite, "check_order_risk", return_value={"status": "PASS", "reasons": []}):
            self.assertEqual(kite._risk_result(order, state, "2026-11-12")["status"], "PASS")

    @mock.patch("builtins.input")
    @mock.patch.object(kite.sys.stdin, "isatty", return_value=True)
    @mock.patch.object(kite, "_today", return_value="2026-11-12")
    @mock.patch.object(kite, "check_order_risk", return_value={"status": "PASS", "reasons": []})
    def test_network_timeout_is_marked_uncertain_and_blocks_retries(
            self, risk_check, _today, _isatty, user_input):
        order = kite._order_from_file(self.order_path)
        fp = kite.fingerprint(order)
        user_input.return_value = "PLACE LIVE %s" % fp
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({"checks": [{"date": "2026-11-12", "fingerprint": fp, "status": "PASS"}],
                       "orders": [{"date": "2026-11-12", "fingerprint": fp, "status": "approved"}]}, fh)
        client = mock.Mock()
        client.orders.return_value = []
        client.place_order.side_effect = kite.requests.exceptions.Timeout("response timed out")
        args = Namespace(order=self.order_path, state=self.state_path, session="unused")
        with mock.patch.object(kite, "_load_kite", return_value=client):
            with self.assertRaisesRegex(kite.KiteError, "may have been accepted"):
                kite.cmd_place(args)
        self.assertEqual(kite._daily_state(self.state_path)["orders"][-1]["status"], "uncertain")
        with self.assertRaisesRegex(kite.KiteError, "unknown outcome"):
            kite.cmd_check(args)
        risk_check.assert_called_once()

    @mock.patch.object(kite, "_today", return_value="2026-11-12")
    def test_approval_requires_a_matching_passing_check(self, _today):
        order = kite._order_from_file(self.order_path)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({"checks": [{"date": "2026-11-12", "fingerprint": kite.fingerprint(order),
                                   "status": "PASS"}], "orders": []}, fh)
        args = Namespace(reply="yes", order=self.order_path, state=self.state_path)
        self.assertEqual(kite.cmd_approve(args), 0)
        state = kite._daily_state(self.state_path)
        self.assertEqual(state["orders"][0]["status"], "approved")

    @mock.patch.object(kite.sys.stdin, "isatty", return_value=False)
    @mock.patch.object(kite, "_today", return_value="2026-11-12")
    def test_place_requires_risk_pass_and_explicit_approval(self, _today, _isatty):
        order = kite._order_from_file(self.order_path)
        fp = kite.fingerprint(order)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({"checks": [{"date": "2026-11-12", "fingerprint": fp, "status": "PASS"}],
                       "orders": [{"date": "2026-11-12", "fingerprint": fp, "status": "approved"}]}, fh)
        args = Namespace(order=self.order_path, state=self.state_path, session="unused")
        with self.assertRaisesRegex(kite.KiteError, "interactive terminal"):
            kite.cmd_place(args)

    @mock.patch("builtins.input", return_value="no")
    @mock.patch.object(kite.sys.stdin, "isatty", return_value=True)
    @mock.patch.object(kite, "_today", return_value="2026-11-12")
    def test_wrong_local_confirmation_never_loads_the_broker(self, _today, _isatty, _input):
        order = kite._order_from_file(self.order_path)
        fp = kite.fingerprint(order)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({"checks": [{"date": "2026-11-12", "fingerprint": fp, "status": "PASS"}],
                       "orders": [{"date": "2026-11-12", "fingerprint": fp, "status": "approved"}]}, fh)
        args = Namespace(order=self.order_path, state=self.state_path, session="unused")
        with mock.patch.object(kite, "_load_kite", side_effect=AssertionError("broker should not load")):
            self.assertEqual(kite.cmd_place(args), 1)


class KiteTelegramQuotes(unittest.TestCase):
    def test_quotes_use_kite_and_do_not_invent_missing_prices(self):
        client = mock.Mock()
        client.ltp.return_value = {"NSE:NIFTY 50": {"last_price": 24100.0}}
        with mock.patch.object(cron_runner, "get_kite_client", return_value=client):
            self.assertEqual(cron_runner.fetch_quotes(), {"NIFTY": 24100.0})
        client.ltp.assert_called_once_with(["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX"])


if __name__ == "__main__":
    unittest.main()
