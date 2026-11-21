import datetime
import unittest

from _load import load

swing = load("trader-scanner", "swing_indian")


def make_bars(closes, start="2024-01-01", volume=10_000_000, spread=1.0):
    """Daily bars on consecutive weekdays, with open = previous close."""
    day = datetime.datetime.strptime(start, "%Y-%m-%d").date()
    bars, prev = [], closes[0]
    for close in closes:
        while day.weekday() >= 5:
            day += datetime.timedelta(days=1)
        bars.append({"date": day.isoformat(), "open": prev, "high": max(prev, close) + spread,
                     "low": min(prev, close) - spread, "close": close, "volume": volume})
        prev = close
        day += datetime.timedelta(days=1)
    return bars


def rising(n, start=100.0, step=0.5):
    return [start + step * k for k in range(n)]


class Indicators(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(swing.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_rsi_extremes(self):
        self.assertEqual(swing.rsi([1, 2, 3, 4, 5], 2)[-1], 100.0)
        self.assertEqual(swing.rsi([5, 4, 3, 2, 1], 2)[-1], 0.0)
        self.assertIsNone(swing.rsi([1, 2, 3], 2)[1])

    def test_atr_of_a_steady_range(self):
        bars = [{"high": 12, "low": 10, "close": 11} for _ in range(40)]
        self.assertAlmostEqual(swing.atr(bars, 14)[-1], 2.0)


class Universe(unittest.TestCase):
    def test_keeps_nse_stocks_that_have_futures(self):
        rows = [
            {"name": "RELIANCE", "segment": "NFO-FUT", "exchange": "NFO", "tradingsymbol": "RELIANCE26NOVFUT",
             "instrument_type": "FUT", "instrument_token": "1"},
            {"name": "NIFTY", "segment": "NFO-FUT", "exchange": "NFO", "tradingsymbol": "NIFTY26NOVFUT",
             "instrument_type": "FUT", "instrument_token": "2"},
            {"name": "RELIANCE INDUSTRIES", "segment": "NSE", "exchange": "NSE", "tradingsymbol": "RELIANCE",
             "instrument_type": "EQ", "instrument_token": "738561"},
            {"name": "SMALLCO", "segment": "NSE", "exchange": "NSE", "tradingsymbol": "SMALLCO",
             "instrument_type": "EQ", "instrument_token": "3"},
            {"name": "RELIANCE INDUSTRIES", "segment": "BSE", "exchange": "BSE", "tradingsymbol": "RELIANCE",
             "instrument_type": "EQ", "instrument_token": "4"},
        ]
        self.assertEqual(swing.build_universe(rows),
                         [{"symbol": "RELIANCE", "token": 738561, "name": "RELIANCE INDUSTRIES"}])

    def test_todays_unfinished_bar_is_dropped_during_the_session(self):
        bars = [{"date": "2026-11-11"}, {"date": "2026-11-12"}]
        self.assertEqual(len(swing.drop_unfinished_bar(bars, datetime.datetime(2026, 11, 12, 11, 0))), 1)
        self.assertEqual(len(swing.drop_unfinished_bar(bars, datetime.datetime(2026, 11, 12, 16, 0))), 2)
        self.assertEqual(len(swing.drop_unfinished_bar(bars, datetime.datetime(2026, 11, 13, 8, 0))), 2)


class Signals(unittest.TestCase):
    def test_pullback_needs_a_sharp_dip_in_an_uptrend(self):
        closes = rising(260)
        dipped = closes + [closes[-1] - 4, closes[-1] - 8]
        bars = make_bars(dipped)
        ind = swing.indicators(bars)
        self.assertTrue(swing.signal("pullback", bars, ind, len(bars) - 1))
        steady = make_bars(closes)
        self.assertFalse(swing.signal("pullback", steady, swing.indicators(steady), len(steady) - 1))

    def test_nothing_fires_below_the_200_day_average(self):
        closes = [300.0 - 0.5 * k for k in range(260)] + [165.0, 160.0]
        bars = make_bars(closes)
        ind = swing.indicators(bars)
        for setup in swing.SETUPS:
            self.assertFalse(swing.signal(setup, bars, ind, len(bars) - 1), setup)

    def test_breakout_needs_volume(self):
        closes = [100.0 + 0.2 * k for k in range(240)] + [148.0] * 21 + [152.0]
        quiet = make_bars(closes)
        self.assertFalse(swing.signal("breakout", quiet, swing.indicators(quiet), len(quiet) - 1))
        loud = make_bars(closes)
        loud[-1]["volume"] *= 2
        self.assertTrue(swing.signal("breakout", loud, swing.indicators(loud), len(loud) - 1))

    def test_illiquid_stocks_never_signal(self):
        closes = rising(260)
        bars = make_bars(closes + [closes[-1] - 4, closes[-1] - 8], volume=1000)
        self.assertFalse(swing.signal("pullback", bars, swing.indicators(bars), len(bars) - 1))


class Trades(unittest.TestCase):
    def setUp(self):
        self.closes = rising(260)

    def trade(self, later_bars, setup="breakout"):
        bars = make_bars(self.closes) + later_bars
        ind = swing.indicators(bars)
        return swing.simulate_trade(setup, bars, ind, 259, 0.0), ind["atr"][259]

    @staticmethod
    def day(n, o, h, l, c):
        return {"date": "2030-01-%02d" % n, "open": o, "high": h, "low": l, "close": c, "volume": 10_000_000}

    def test_target_is_two_times_the_risk(self):
        entry = 230.0
        trade, atr_now = self.trade([self.day(1, entry, entry + 1, entry - 1, entry),
                                     self.day(2, entry, entry + 5 * atr_now_guess(), entry - 1, entry + 3)])
        self.assertEqual(trade["reason"], "target")
        self.assertAlmostEqual(trade["net_r"], 2.0, places=2)
        self.assertAlmostEqual(trade["exit"], round(entry + 4 * atr_now, 2), places=2)

    def test_gap_below_the_stop_fills_at_the_open(self):
        entry = 230.0
        trade, atr_now = self.trade([self.day(1, entry, entry + 1, entry - 1, entry),
                                     self.day(2, 200.0, 201.0, 199.0, 200.0)])
        self.assertEqual((trade["reason"], trade["exit"]), ("stop", 200.0))
        self.assertLess(trade["net_r"], -1.0)

    def test_stop_wins_when_one_day_touches_both(self):
        entry = 230.0
        trade, _ = self.trade([self.day(1, entry, entry + 50, entry - 50, entry)])
        self.assertEqual(trade["reason"], "stop")
        self.assertAlmostEqual(trade["net_r"], -1.0, places=2)

    def test_unfinished_trade_is_not_counted(self):
        entry = 230.0
        trade, _ = self.trade([self.day(1, entry, entry + 1, entry - 1, entry)])
        self.assertIsNone(trade)

    def test_costs_reduce_the_result(self):
        bars = make_bars(self.closes) + [self.day(1, 230.0, 231.0, 229.0, 230.0),
                                         self.day(2, 200.0, 201.0, 199.0, 200.0)]
        ind = swing.indicators(bars)
        free = swing.simulate_trade("breakout", bars, ind, 259, 0.0)
        paid = swing.simulate_trade("breakout", bars, ind, 259, 1.0)
        self.assertAlmostEqual(free["net_pts"] - paid["net_pts"], 2.3, places=2)


def atr_now_guess():
    # the rising series moves 0.5 a day with a 1.0 spread each side: ATR is 2.5
    return 2.5


class Momentum(unittest.TestCase):
    def test_score_skips_the_latest_month(self):
        closes = [100.0] * 232 + [200.0] * 21
        self.assertAlmostEqual(swing.momentum_score(closes, 252), 0.0)
        closes = [100.0] * 200 + [150.0] * 53
        self.assertAlmostEqual(swing.momentum_score(closes, 252), 0.5)
        self.assertIsNone(swing.momentum_score(closes, 251))

    def market(self, winners_keep_winning):
        """30 stocks: five strong ones that keep rising (or stall), and 25 slow ones."""
        days = 420
        universe, data = [], {}
        for n in range(30):
            symbol = "S%02d" % n
            strong = n < 5
            closes = []
            price = 100.0
            for k in range(days):
                step = 0.4 if strong else 0.05
                if strong and k >= 270 and not winners_keep_winning:
                    step = -0.3
                price += step
                closes.append(price)
            data[symbol] = make_bars(closes)
            universe.append({"symbol": symbol, "token": n, "name": symbol})
        calendar = [b["date"] for b in data["S00"]]
        return universe, data, calendar

    def test_basket_beats_the_market_when_winners_keep_winning(self):
        universe, data, calendar = self.market(True)
        spec = dict(swing.MOMENTUM, top_n=5)
        stats = swing.run_momentum_backtest(data, universe, calendar, 0.3, spec)
        self.assertGreater(stats["periods"], 5)
        self.assertGreater(stats["edge_over_holding_pct"], 0)
        self.assertEqual(stats["grade"], "SUPPORTED")
        self.assertIn("with_emergency_stop", stats)

    def test_basket_fails_when_winners_reverse(self):
        universe, data, calendar = self.market(False)
        spec = dict(swing.MOMENTUM, top_n=5)
        stats = swing.run_momentum_backtest(data, universe, calendar, 0.3, spec)
        self.assertLess(stats["edge_over_holding_pct"], 0)
        self.assertEqual(stats["grade"], "FAILED")

    def test_every_start_day_is_tested(self):
        universe, data, calendar = self.market(True)
        spec = dict(swing.MOMENTUM, top_n=5, hold_days=10)
        stats = swing.run_momentum_backtest(data, universe, calendar, 0.3, spec)
        self.assertEqual(stats["start_days_tested"], 10)
        self.assertEqual(stats["basket"], 5)
        low, high = stats["edge_range_pct"]
        self.assertLessEqual(low, stats["edge_over_holding_pct"])
        self.assertGreaterEqual(high, stats["edge_over_holding_pct"])

    def test_a_stock_that_stays_in_the_basket_pays_costs_once(self):
        # The same five stocks lead throughout, so after the first period nothing is replaced
        # and a higher cost barely moves the basket's average.
        universe, data, calendar = self.market(True)
        spec = dict(swing.MOMENTUM, top_n=5, hold_days=10)
        cheap = swing.run_momentum_backtest(data, universe, calendar, 0.0, spec, False)
        dear = swing.run_momentum_backtest(data, universe, calendar, 1.0, spec, False)
        self.assertLess(dear["replaced_per_period_pct"], 15)
        self.assertLess(cheap["avg_net_pct"] - dear["avg_net_pct"], 0.15)
        self.assertGreater(cheap["avg_net_pct"], dear["avg_net_pct"])

    def test_carried_position_runs_from_the_last_close_without_costs(self):
        bars = make_bars([100.0, 100.0, 110.0, 121.0])
        bars[1]["open"] = 105.0
        fresh = swing._hold(bars, 1.0, 0, 2, None, 1.0)
        kept = swing._hold(bars, 1.0, 0, 2, None, 1.0, carried=True)
        self.assertAlmostEqual(fresh, 110.0 / 105.0 - 1.0 - 0.01)
        self.assertAlmostEqual(kept, 0.10)

    def test_flat_charge_weighs_more_on_a_small_position(self):
        self.assertAlmostEqual(swing.effective_cost_pct(0.30, 15.0, 5000), 0.60)
        self.assertAlmostEqual(swing.effective_cost_pct(0.30, 15.0, 50000), 0.33)
        self.assertAlmostEqual(swing.effective_cost_pct(0.30, 0.0, 5000), 0.30)

    def test_picks_are_the_top_of_the_ranking_with_sizes_inside_the_limits(self):
        universe, data, calendar = self.market(True)
        report = {"momentum": {"grade": "MODEST"}}
        picks, latest = swing.find_picks(data, universe, report, budget=50000, max_loss=2000)
        momentum = [p for p in picks if p["setup"] == "momentum"]
        self.assertEqual(latest, calendar[-1])
        self.assertEqual(len(momentum), swing.MOMENTUM["top_n"])
        self.assertEqual({p["symbol"] for p in momentum[:5]}, {"S00", "S01", "S02", "S03", "S04"})
        for p in momentum:
            self.assertEqual(p["stop_kind"], "emergency")
            self.assertLess(p["stop"], p["close"])
            self.assertLessEqual(p["position_inr"], 5000)
            self.assertLessEqual(p["max_loss_inr"], 2000)
            self.assertIsNone(p["max_entry"])  # the tested rule buys at the open, with no limit

    def test_a_stock_too_dear_for_one_position_is_passed_over_not_counted(self):
        universe, data, calendar = self.market(True)
        report = {"momentum": {"grade": "MODEST"}}
        # 5 positions of 250 each: the strong stocks (above 250 a share) cannot be bought
        spec = dict(swing.MOMENTUM, top_n=5)
        picks, _ = swing.find_picks(data, universe, report, budget=1250, max_loss=2000, spec=spec)
        momentum = [p for p in picks if p["setup"] == "momentum"]
        self.assertEqual(sum(1 for p in momentum if p["qty"] > 0), 5)
        self.assertEqual({p["symbol"] for p in momentum if p["qty"] == 0}, {"S00", "S01", "S02", "S03", "S04"})
        self.assertEqual([p["momentum_place"] for p in momentum], list(range(1, len(momentum) + 1)))

    def test_buy_and_sell_dates_skip_weekends_and_holidays(self):
        # Signal on Thursday 12 Nov 2026: buy Friday 13th; Tuesday 24th is a holiday,
        # so the tenth trading day is Friday 27th.
        self.assertEqual(swing.trading_dates_after("2026-11-12", 10), ("2026-11-13", "2026-11-27"))
        self.assertEqual(swing.trading_dates_after("2026-11-12", 21)[0], "2026-11-13")


class Grades(unittest.TestCase):
    BASE = {"trades": 500, "avg_net_r": 0.1, "net_r_95ci": [0.02, 0.18],
            "first_half_avg_net_r": 0.1, "second_half_avg_net_r": 0.1}

    def test_grades(self):
        self.assertEqual(swing.grade(self.BASE, 0.5)[0], "SUPPORTED")
        self.assertEqual(swing.grade(self.BASE, -0.1)[0], "UNPROVEN")
        self.assertEqual(swing.grade(dict(self.BASE, second_half_avg_net_r=-0.1), 0.5)[0], "UNPROVEN")
        self.assertEqual(swing.grade(dict(self.BASE, avg_net_r=-0.1), 0.5)[0], "FAILED")
        self.assertEqual(swing.grade(dict(self.BASE, trades=20), 0.5)[0], "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
