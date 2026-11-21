import datetime
import unittest
from unittest import mock

from _load import load

monitor = load("trader-alerts", "swing_monitor")

WATCH = {"signal_date": "2026-11-12", "buy_date": "2026-11-13", "sell_date": "2026-11-27",
         "monitor_until": "2026-11-20", "evidence": {"avg_net_pct": 0.69, "edge_over_holding_pct": 0.48}}
POSITION = {"symbol": "BHEL", "name": "BHEL", "momentum_place": 5, "planned_qty": 20,
            "close_at_signal": 100.0, "max_entry": 102.0, "stop": 84.0, "actual_entry": None, "actual_qty": None}


def bar(date, o, h, l, c):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": 1000}


def history(*later):
    """Sixty flat days at 100 ending 12 Nov, then the given bars."""
    day = datetime.date(2026, 11, 12)
    bars = []
    while len(bars) < 60:
        if day.weekday() < 5:
            bars.append(bar(day.isoformat(), 100, 101, 99, 100))
        day -= datetime.timedelta(days=1)
    return bars[::-1] + list(later)


NIFTY = history(bar("2026-11-13", 25000, 25300, 24900, 25250))


class Assess(unittest.TestCase):
    def test_before_the_buy_date_it_waits(self):
        row = monitor.assess(POSITION, history(), history(), WATCH, "2026-11-12")
        self.assertEqual(row["decision"], "WAIT")
        self.assertNotIn("pnl_inr", row)

    def test_progress_is_measured_from_the_buy_day_open(self):
        bars = history(bar("2026-11-13", 101, 106, 100, 105))
        row = monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-13")
        self.assertEqual(row["decision"], "HOLD")
        self.assertAlmostEqual(row["entry"], 101)
        self.assertAlmostEqual(row["pnl_inr"], 80.0)
        self.assertAlmostEqual(row["since_entry_pct"], (105 / 101 - 1) * 100)
        self.assertAlmostEqual(row["nifty_since_pct"], 1.0)
        self.assertAlmostEqual(row["vs_nifty_pct"], row["since_entry_pct"] - 1.0)
        self.assertEqual((row["day_number"], row["days_left"]), (1, 9))

    def test_your_own_fill_replaces_the_assumed_one(self):
        mine = dict(POSITION, actual_entry=103.0, actual_qty=10)
        row = monitor.assess(mine, history(bar("2026-11-13", 101, 106, 100, 105)), NIFTY, WATCH, "2026-11-13")
        self.assertTrue(row["real_fill"])
        self.assertAlmostEqual(row["pnl_inr"], 20.0)

    def test_a_skipped_stock_has_no_profit_or_loss(self):
        row = monitor.assess(dict(POSITION, actual_qty=0), history(bar("2026-11-13", 101, 106, 100, 105)),
                             NIFTY, WATCH, "2026-11-13")
        self.assertEqual(row["decision"], "SKIPPED")
        self.assertNotIn("pnl_inr", row)

    def test_open_above_the_buy_limit_says_do_not_chase(self):
        row = monitor.assess(POSITION, history(bar("2026-11-13", 104, 106, 103, 105)), NIFTY, WATCH, "2026-11-13")
        self.assertEqual((row["decision"], row["severity"]), ("DO NOT CHASE", "act"))

    def test_without_a_buy_limit_a_high_open_is_just_a_hold(self):
        free = dict(POSITION, max_entry=None)
        row = monitor.assess(free, history(bar("2026-11-13", 104, 106, 103, 105)), NIFTY, WATCH, "2026-11-13")
        self.assertEqual(row["decision"], "HOLD")
        self.assertIn("at the open", monitor.assess(free, history(), history(), WATCH, "2026-11-12")["reason"])
        summary = monitor.summarize([row], NIFTY, WATCH)
        page = monitor.render_html([row], summary, WATCH, datetime.datetime(2026, 11, 13, 12, 30), "", None)
        self.assertNotIn("buy limit", page)

    def test_plan_length_comes_from_the_watch_dates_and_rank_from_its_basket(self):
        bars = history(bar("2026-11-13", 101, 106, 100, 105))
        row = monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-13", rank=12)
        self.assertEqual((row["plan_days"], row["decision"]), (10, "HOLD, DO NOT RENEW"))
        row = monitor.assess(POSITION, bars, NIFTY, dict(WATCH, basket=20), "2026-11-13", rank=12)
        self.assertEqual(row["decision"], "HOLD")

    def test_touching_the_emergency_stop_means_exit(self):
        bars = history(bar("2026-11-13", 101, 102, 95, 96), bar("2026-11-16", 95, 96, 83, 90))
        row = monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-17")
        self.assertEqual((row["decision"], row["severity"]), ("EXIT", "act"))
        self.assertIn("2026-11-16", row["reason"])

    def test_close_to_the_stop_is_a_warning(self):
        bars = history(bar("2026-11-13", 101, 102, 86, 87))
        row = monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-13")
        self.assertEqual((row["decision"], row["severity"]), ("WATCH", "warn"))

    def test_exit_day_and_the_day_before(self):
        bars = history(bar("2026-11-13", 101, 106, 100, 105))
        self.assertEqual(monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-27")["decision"], "SELL TODAY")
        self.assertEqual(monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-26")["decision"], "EXIT TOMORROW")

    def test_falling_out_of_the_top_twenty_is_noted_but_not_an_alarm(self):
        bars = history(bar("2026-11-13", 101, 106, 100, 105))
        row = monitor.assess(POSITION, bars, NIFTY, WATCH, "2026-11-13", rank=31)
        self.assertEqual((row["decision"], row["severity"]), ("HOLD, DO NOT RENEW", "info"))

    def test_missing_prices_ask_for_a_check(self):
        row = monitor.assess(POSITION, [], NIFTY, WATCH, "2026-11-13")
        self.assertEqual(row["decision"], "CHECK")

    def test_trading_day_count_skips_weekend_and_holiday(self):
        self.assertEqual(monitor.trading_days_between("2026-11-13", "2026-11-27"), 9)
        self.assertEqual(monitor.trading_days_between("2026-11-27", "2026-11-27"), 0)


class Report(unittest.TestCase):
    def rows(self):
        good = monitor.assess(POSITION, history(bar("2026-11-13", 101, 106, 100, 105)), NIFTY, WATCH, "2026-11-13")
        other = dict(POSITION, symbol="MCX", name="M&M <test>")
        bad = monitor.assess(other, history(bar("2026-11-13", 101, 102, 83, 85)), NIFTY, WATCH, "2026-11-13")
        return [good, bad]

    def test_summary_adds_up_and_lists_decisions(self):
        rows = self.rows()
        summary = monitor.summarize(rows, NIFTY, WATCH)
        self.assertEqual(summary["positions"], 2)
        self.assertAlmostEqual(summary["pnl_inr"], 80.0 - 320.0)
        self.assertAlmostEqual(summary["invested_inr"], 4040.0)
        self.assertEqual([r["symbol"] for r in summary["decisions"]], ["MCX"])
        self.assertAlmostEqual(summary["loss_at_stops_inr"], 2 * 20 * 17)

    def test_subject_and_html(self):
        rows = self.rows()
        summary = monitor.summarize(rows, NIFTY, WATCH)
        now = datetime.datetime(2026, 11, 13, 12, 30)
        subject = monitor.subject_line(summary, now)
        self.assertIn("1 action needed", subject)
        page = monitor.render_html(rows, summary, WATCH, now, "Nifty is up", "2026-11-12")
        self.assertIn("Decisions for you", page)
        self.assertIn("EXIT", page)
        self.assertIn("M&amp;M &lt;test&gt;", page)  # names are escaped
        self.assertNotIn("<test>", page)
        text = monitor.render_text(rows, summary, WATCH, now)
        self.assertIn("MCX: EXIT", text)

    def test_quiet_day_says_no_action(self):
        rows = self.rows()[:1]
        summary = monitor.summarize(rows, NIFTY, WATCH)
        self.assertIn("no action needed", monitor.subject_line(summary, datetime.datetime(2026, 11, 13, 12, 30)))
        self.assertIn("No decision needed", monitor.render_html(rows, summary, WATCH,
                                                                 datetime.datetime(2026, 11, 13, 12, 30), "", None))


class WatchList(unittest.TestCase):
    def test_takes_usable_momentum_picks_only(self):
        doc = {"signal_date": "2026-11-12", "momentum_buy_date": "2026-11-13", "momentum_sell_date": "2026-11-27",
               "setups": {"momentum": {"grade": "MODEST"}},
               "picks": [
                   {"symbol": "A", "name": "A", "setup": "momentum", "grade": "MODEST", "qty": 5, "close": 10,
                    "max_entry": 11, "stop": 8, "momentum_place": 1},
                   {"symbol": "B", "name": "B", "setup": "momentum", "grade": "MODEST", "qty": 0, "close": 10,
                    "max_entry": 11, "stop": 8, "momentum_place": 2},
                   {"symbol": "C", "name": "C", "setup": "reclaim", "grade": "UNPROVEN", "qty": 5, "close": 10,
                    "max_entry": 11, "stop": 8},
                   {"symbol": "D", "name": "D", "setup": "momentum", "grade": "MODEST", "qty": 3, "close": 10,
                    "max_entry": 11, "stop": 8, "momentum_place": 3}]}
        watch = monitor.build_watch(doc, top=5, until="2026-11-20")
        self.assertEqual([p["symbol"] for p in watch["positions"]], ["A", "D"])
        self.assertEqual((watch["buy_date"], watch["sell_date"], watch["monitor_until"]),
                         ("2026-11-13", "2026-11-27", "2026-11-20"))


class Email(unittest.TestCase):
    def test_refuses_without_settings(self):
        with self.assertRaisesRegex(RuntimeError, "smtp_password"):
            monitor.send_email("s", "t", "<p>h</p>", {"to": "a@example.com", "user": "b@example.com",
                                                      "password": None, "host": "h", "port": 587})

    def test_sends_one_message_with_text_and_html(self):
        smtp = mock.MagicMock()
        server = smtp.return_value.__enter__.return_value
        monitor.send_email("Subject", "plain", "<p>rich</p>",
                           {"to": "a@example.com", "user": "b@example.com", "password": "abcd efgh",
                            "host": "smtp.example.com", "port": 587}, smtp_class=smtp)
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("b@example.com", "abcdefgh")
        message = server.send_message.call_args[0][0]
        self.assertEqual((message["To"], message["From"], message["Subject"]),
                         ("a@example.com", "b@example.com", "Subject"))
        self.assertTrue(message.is_multipart())


if __name__ == "__main__":
    unittest.main()
