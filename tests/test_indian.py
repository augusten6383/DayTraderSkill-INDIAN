import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from _load import load

calendar = load(".", "market_calendar_indian")
instruments = load(".", "indian_instruments")
size = load("trader-budget", "size_indian")
check = load("trader-risk", "check_indian")
entry = load("trader-entry", "entry_indian")
backtest = load("trader-timemachine", "backtest_indian")
cron_runner = load("telegram_bot", "cron_runner")

OPEN_DAY = datetime.datetime(2026, 11, 12, 10, 30)  # a Thursday, mid-session IST


def bar(time, o, h, l, c, date="2026-11-12"):
    return {"date": date, "time": time, "open": o, "high": h, "low": l, "close": c, "volume": 0}


# Range 100-110 (midpoint 105), then an upside break at 09:30 and an entry at the 09:35 open.
RANGE = [bar("09:15", 104, 108, 100, 106), bar("09:20", 106, 110, 105, 107), bar("09:25", 107, 109, 104, 108)]
BREAK_UP = RANGE + [bar("09:30", 108, 112, 108, 111), bar("09:35", 111, 112, 110, 111)]
NO_COSTS = {"slippage_pct": 0.0, "cost_pct": 0.0}


class Calendar(unittest.TestCase):
    def test_official_2026_holidays(self):
        for day in ("2026-01-15", "2026-03-26", "2026-03-31", "2026-05-28", "2026-06-26",
                    "2026-09-14", "2026-11-10", "2026-11-24", "2026-12-25"):
            when = datetime.datetime.strptime(day + " 11:00", "%Y-%m-%d %H:%M")
            self.assertFalse(calendar.is_market_open(when)[0], day)

    def test_days_the_old_list_wrongly_closed_are_open(self):
        for day in ("2026-03-20", "2026-05-27", "2026-11-09"):
            when = datetime.datetime.strptime(day + " 11:00", "%Y-%m-%d %H:%M")
            self.assertTrue(calendar.is_market_open(when)[0], day)

    def test_a_year_without_a_holiday_list_says_so(self):
        with mock.patch.object(calendar, "_cached_holidays", return_value={}):
            is_open, reason = calendar.is_market_open(datetime.datetime(2027, 1, 26, 11, 0))
        self.assertTrue(is_open)
        self.assertIn("no 2027 holiday list", reason)

    def test_next_open_skips_weekend_and_holiday(self):
        # Friday 6 Nov after the close -> Monday 9 Nov; Tuesday 10 Nov is Balipratipada.
        self.assertEqual(calendar.next_market_open(datetime.datetime(2026, 11, 6, 16, 0)),
                         datetime.datetime(2026, 11, 9, 9, 15))
        self.assertEqual(calendar.next_market_open(datetime.datetime(2026, 11, 9, 16, 0)),
                         datetime.datetime(2026, 11, 11, 9, 15))

    def test_import_reads_nse_json(self):
        with tempfile.TemporaryDirectory() as temp:
            source = os.path.join(temp, "nse.json")
            target = os.path.join(temp, "holidays.json")
            with open(source, "w", encoding="utf-8") as fh:
                json.dump({"CM": [{"tradingDate": "26-Jan-2027", "description": "Republic Day"}]}, fh)
            self.assertEqual(calendar.import_holidays(source, target), {"2027-01-26": "Republic Day"})
            with open(target, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["holidays"], {"2027-01-26": "Republic Day"})


class LotSizes(unittest.TestCase):
    CONFIG = {"indices": {"NIFTY": {"lot_size": 65}, "BANKNIFTY": {"lot_size": 30},
                          "SENSEX": {"lot_size": 20}}}

    def test_banknifty_is_not_read_as_nifty(self):
        for symbol, name in (("BANKNIFTY", "BANKNIFTY"), ("BANK NIFTY", "BANKNIFTY"),
                             ("BANKNIFTY26NOV52000CE", "BANKNIFTY"), ("NIFTY BANK", "BANKNIFTY"),
                             ("NIFTY", "NIFTY"), ("NIFTY 50", "NIFTY"), ("NIFTY26N1725300PE", "NIFTY"),
                             ("SENSEX26N1283000CE", "SENSEX")):
            self.assertEqual(instruments.underlying_of(symbol), name, symbol)
        self.assertEqual(instruments.lot_size_for("BANKNIFTY26NOV52000CE", self.CONFIG), 30)
        self.assertEqual(instruments.lot_size_for("NIFTY", self.CONFIG), 65)

    def test_stocks_etfs_and_other_indices_are_not_index_lots(self):
        for symbol in ("RELIANCE", "NIFTYBEES", "FINNIFTY", "INFY"):
            self.assertIsNone(instruments.underlying_of(symbol), symbol)
            self.assertEqual(instruments.lot_size_for(symbol, self.CONFIG), 1)

    def test_refresh_takes_the_nearest_expiry_lot(self):
        rows = [
            {"name": "SENSEX", "segment": "BFO-OPT", "expiry": "2027-01-28", "lot_size": "25"},
            {"name": "SENSEX", "segment": "BFO-OPT", "expiry": "2026-11-19", "lot_size": "20"},
            {"name": "SENSEX", "segment": "BFO-OPT", "expiry": "2026-11-05", "lot_size": "10"},
            {"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "lot_size": "999"},
            {"name": "NIFTY", "segment": "NFO-OPT", "expiry": "2026-11-17", "lot_size": "65"},
        ]
        found = instruments.parse_lot_sizes(rows, today="2026-11-12")
        self.assertEqual(found["SENSEX"], {"lot_size": 20, "expiry": "2026-11-19"})
        self.assertEqual(found["NIFTY"]["lot_size"], 65)

    def test_shipped_config_has_current_lots(self):
        self.assertEqual(instruments.lot_size_for("NIFTY"), 65)
        self.assertEqual(instruments.lot_size_for("BANKNIFTY"), 30)
        self.assertEqual(instruments.lot_size_for("SENSEX"), 20)


class Sizer(unittest.TestCase):
    def test_sizes_in_whole_lots_of_the_right_index(self):
        result = size.calculate_option_lots("BANKNIFTY", 50000, 125, 95, 2000)
        self.assertEqual((result["lot_size"], result["lots"], result["total_qty"]), (30, 2, 60))
        self.assertEqual(result["max_risk_inr"], 1800)

    def test_stop_at_or_above_entry_is_refused(self):
        for stop in (125, 130):
            result = size.calculate_option_lots("NIFTY", 50000, 125, stop, 2000)
            self.assertEqual(result["lots"], 0)
            self.assertIn("REJECTED", result["status"])


class RiskCheck(unittest.TestCase):
    def run_check(self, **kwargs):
        with mock.patch.object(check, "to_ist", return_value=OPEN_DAY):
            return check.check_order_risk(**kwargs)

    def test_a_good_order_passes(self):
        result = self.run_check(symbol="NIFTY26N1725300CE", qty=65, entry=125, stop=100)
        self.assertEqual(result["status"], "PASS", result["reasons"])

    def test_stop_on_the_wrong_side_blocks(self):
        result = self.run_check(symbol="NIFTY", qty=65, entry=125, stop=130)
        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(any("BAD_STOP" in r for r in result["reasons"]))
        short = self.run_check(symbol="INFY", qty=10, entry=1500, stop=1490, side="sell")
        self.assertTrue(any("BAD_STOP" in r for r in short["reasons"]))

    def test_swing_basket_has_its_own_day_limits(self):
        cfg = {"max_trades_per_day": 3, "max_daily_loss_inr": 5000,
               "swing_max_trades_per_day": 10, "swing_max_daily_loss_inr": 10000}
        self.assertEqual(check.day_limits(cfg), (3, 5000))
        self.assertEqual(check.day_limits(cfg, swing=True), (10, 10000))
        # without swing keys the intraday limits still guard a swing order
        self.assertEqual(check.day_limits({"max_trades_per_day": 3, "max_daily_loss_inr": 5000}, swing=True), (3, 5000))

    def test_fourth_trade_of_the_day_is_blocked_intraday_but_not_for_the_basket(self):
        cfg = {"max_loss_per_trade_inr": 2000, "max_trades_per_day": 3, "max_daily_loss_inr": 5000,
               "swing_max_trades_per_day": 10, "swing_max_daily_loss_inr": 10000}
        with mock.patch.object(check, "load_config", return_value=cfg):
            intraday = check.check_order_risk("BHEL", 10, 430.0, 360.0, realized_loss_today=3000, trades_today=3)
            basket = check.check_order_risk("BHEL", 10, 430.0, 360.0, realized_loss_today=3000, trades_today=3,
                                           swing=True)
            full = check.check_order_risk("BHEL", 10, 430.0, 360.0, realized_loss_today=3000, trades_today=10,
                                         swing=True)
        self.assertTrue(any(r.startswith("TRADES_LIMIT") for r in intraday["reasons"]))
        self.assertFalse(any(r.startswith("TRADES_LIMIT") for r in basket["reasons"]))
        self.assertTrue(any(r.startswith("TRADES_LIMIT") for r in full["reasons"]))

    def test_banknifty_uses_its_own_lot(self):
        ok = self.run_check(symbol="BANKNIFTY", qty=30, entry=125, stop=100)
        self.assertEqual(ok["status"], "PASS", ok["reasons"])
        bad = self.run_check(symbol="BANKNIFTY", qty=65, entry=125, stop=120)
        self.assertTrue(any("BANKNIFTY lot size (30)" in r for r in bad["reasons"]))


class EntryRule(unittest.TestCase):
    def test_needs_all_three_range_bars(self):
        self.assertEqual(entry.opening_range(RANGE), (110, 100))
        self.assertIsNone(entry.opening_range(RANGE[1:]))

    def test_first_close_outside_the_range_is_the_signal(self):
        self.assertEqual(entry.first_breakout(BREAK_UP), (3, "long"))
        self.assertIsNone(entry.first_breakout(BREAK_UP, direction="short"))
        down = RANGE + [bar("09:30", 104, 105, 98, 99)]
        self.assertEqual(entry.first_breakout(down), (3, "short"))

    def test_a_wick_above_the_range_is_not_a_signal(self):
        wick = RANGE + [bar("09:30", 108, 115, 107, 109)]
        self.assertIsNone(entry.first_breakout(wick))

    def test_no_signal_after_the_last_entry_time(self):
        late = RANGE + [bar("11:35", 108, 112, 108, 111)]
        self.assertIsNone(entry.first_breakout(late, last_entry="11:30"))

    def test_a_bar_still_forming_does_not_trigger(self):
        forming = datetime.datetime(2026, 11, 12, 9, 33)
        result = entry.evaluate_orb_entry("^NSEI", now_ist=forming, bars=BREAK_UP[:4])
        self.assertEqual(result["status"], "WAITING")
        closed = datetime.datetime(2026, 11, 12, 9, 35)
        result = entry.evaluate_orb_entry("^NSEI", now_ist=closed, bars=BREAK_UP[:4])
        self.assertEqual((result["status"], result["side"], result["bar_time"]), ("TRIGGERED", "long", "09:30"))

    def test_missing_range_bars_give_no_signal(self):
        result = entry.evaluate_orb_entry("^NSEI", now_ist=OPEN_DAY, bars=BREAK_UP[1:])
        self.assertEqual(result["status"], "NO_DATA")

    def test_parse_chart_drops_gaps_and_the_live_tick(self):
        base = int(datetime.datetime(2026, 11, 12, 3, 45, tzinfo=datetime.timezone.utc).timestamp())
        data = {"chart": {"result": [{"timestamp": [base, base + 300, base + 437], "indicators": {"quote": [{
            "open": [1, None, 3], "high": [2, None, 3], "low": [1, None, 3], "close": [2, None, 3],
            "volume": [0, None, 0]}]}}]}}
        bars = entry.parse_chart(data)
        self.assertEqual([(b["date"], b["time"]) for b in bars], [("2026-11-12", "09:15")])


class Backtest(unittest.TestCase):
    def test_target_hit(self):
        day = BREAK_UP + [bar("09:40", 111, 121, 110, 120)]
        trade = backtest.simulate_day(day, **NO_COSTS)
        # entry 111, stop 105 (risk 6), target 111 + 1.5 * 6 = 120
        self.assertEqual((trade["entry"], trade["stop"], trade["target"]), (111, 105, 120))
        self.assertEqual((trade["reason"], trade["net_r"]), ("target", 1.5))

    def test_stop_wins_when_one_bar_touches_both(self):
        day = BREAK_UP + [bar("09:40", 111, 125, 104, 120)]
        trade = backtest.simulate_day(day, **NO_COSTS)
        self.assertEqual((trade["reason"], trade["net_r"]), ("stop", -1.0))

    def test_gap_through_the_stop_fills_at_the_gap(self):
        day = BREAK_UP + [bar("09:40", 102, 103, 101, 102)]
        trade = backtest.simulate_day(day, **NO_COSTS)
        self.assertEqual((trade["reason"], trade["exit"], trade["net_r"]), ("stop", 102, -1.5))

    def test_flat_at_square_off_time(self):
        day = BREAK_UP + [bar("15:10", 111, 113, 110, 112), bar("15:15", 114, 115, 113, 114)]
        trade = backtest.simulate_day(day, **NO_COSTS)
        self.assertEqual((trade["reason"], trade["exit_time"], trade["exit"]), ("time", "15:15", 114))

    def test_short_side_mirrors_the_long(self):
        day = RANGE + [bar("09:30", 104, 105, 98, 99), bar("09:35", 99, 100, 89, 90)]
        trade = backtest.simulate_day(day, **NO_COSTS)
        # entry 99, stop 105 (risk 6), target 90
        self.assertEqual((trade["side"], trade["target"], trade["reason"], trade["net_r"]),
                         ("short", 90, "target", 1.5))

    def test_costs_come_out_of_the_result(self):
        day = BREAK_UP + [bar("09:40", 111, 121, 110, 120)]
        trade = backtest.simulate_day(day, slippage_pct=0.5, cost_pct=1.0)
        # 2% of the 111 entry = 2.22 points
        self.assertEqual(trade["costs_pts"], 2.22)
        self.assertEqual(trade["net_pts"], 6.78)

    def test_no_trade_without_a_bar_to_enter_on(self):
        self.assertIsNone(backtest.simulate_day(BREAK_UP[:4], **NO_COSTS))
        self.assertIsNone(backtest.simulate_day(RANGE, **NO_COSTS))

    def test_range_filter_skips_the_day(self):
        day = BREAK_UP + [bar("09:40", 111, 121, 110, 120)]
        self.assertIsNone(backtest.simulate_day(day, max_range_pct=5.0, **NO_COSTS))

    def test_summary_and_verdicts(self):
        self.assertIn("No trades", backtest.summarize([], 5)["verdict"])
        losing = [{"date": "2026-01-%02d" % (i + 1), "side": "long", "reason": "stop", "net_r": -1.0,
                   "gross_r": -1.0, "net_pts": -10.0, "costs_pts": 1.0} for i in range(40)]
        stats = backtest.summarize(losing, 40)
        self.assertEqual((stats["trades"], stats["win_rate_pct"], stats["max_drawdown_r"]), (40, 0.0, 40.0))
        self.assertIn("No edge", stats["verdict"])
        self.assertIn("Too few", backtest.summarize(losing[:10], 10)["verdict"])
        winning = [dict(t, net_r=1.0 + (i % 2) * 0.5, gross_r=1.5, net_pts=10.0, reason="target")
                   for i, t in enumerate(losing)]
        self.assertIn("Positive after costs", backtest.summarize(winning, 40)["verdict"])

    def test_run_groups_bars_into_sessions(self):
        day_one = BREAK_UP + [bar("09:40", 111, 121, 110, 120)]
        day_two = [dict(b, date="2026-11-13") for b in day_one]
        trades, stats = backtest.run(day_two + day_one, **NO_COSTS)
        self.assertEqual([t["date"] for t in trades], ["2026-11-12", "2026-11-13"])
        self.assertEqual(stats["days_tested"], 2)


class TelegramAlert(unittest.TestCase):
    RESULT = {"status": "TRIGGERED", "side": "short", "bar_time": "10:00", "trigger_price": 98.0,
              "or_high": 110.0, "or_low": 100.0}

    def test_fresh_break_becomes_an_alert_plan(self):
        plan = cron_runner.orb_alert_plan(self.RESULT, datetime.datetime(2026, 11, 12, 10, 10))
        # short from 98, stop at the 105 midpoint (risk 7), target 98 - 1.5 * 7
        self.assertEqual((plan["side"], plan["stop"], plan["target"]), ("short", 105.0, 87.5))

    def test_stale_or_untriggered_results_send_nothing(self):
        self.assertIsNone(cron_runner.orb_alert_plan(self.RESULT, datetime.datetime(2026, 11, 12, 11, 0)))
        self.assertIsNone(cron_runner.orb_alert_plan({"status": "WAITING"}, OPEN_DAY))

    def test_one_alert_per_fresh_break(self):
        results = {"^NSEI": self.RESULT, "^NSEBANK": {"status": "WAITING", "reason": "inside range"}}
        with mock.patch.object(cron_runner, "evaluate_orb_entry",
                               side_effect=lambda symbol, direction, now_ist: results[symbol]), \
                mock.patch.object(cron_runner, "send_orb_alert", return_value=True) as send:
            self.assertEqual(cron_runner.check_breakouts(datetime.datetime(2026, 11, 12, 10, 10)), 1)
        send.assert_called_once()
        self.assertEqual(send.call_args[0][0], "NIFTY")


if __name__ == "__main__":
    unittest.main()
