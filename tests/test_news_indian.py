import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from _load import FIX, load

ni = load("trader-news", "news_indian")
news = ni.news
DIR = os.path.join(FIX, "trader-news")
# Real Yahoo chart and Google News responses for MCX and Bank of Maharashtra, saved on 21 Nov 2026
NOW = "2026-11-21T06:30:00+00:00"


def raw(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ni.main(args)
    return code, out.getvalue(), err.getvalue()


class Symbols(unittest.TestCase):
    def test_exchange_suffix_is_kept_and_share_class_is_not(self):
        self.assertEqual(news.yahoo_symbol("MCX.NS"), "MCX.NS")
        self.assertEqual(news.yahoo_symbol("reliance.bo"), "RELIANCE.BO")
        self.assertEqual(news.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(news.yahoo_symbol("TSLA"), "TSLA")

    def test_nse_symbols(self):
        self.assertEqual(ni.nse_yahoo("mcx"), "MCX.NS")
        self.assertEqual(ni.nse_yahoo("BAJAJ-AUTO"), "BAJAJ-AUTO.NS")
        self.assertEqual(ni.nse_yahoo("MCX.BO"), "MCX.BO")
        self.assertEqual(ni.plain("MCX.NS"), "MCX")


class Names(unittest.TestCase):
    def test_key_phrase(self):
        self.assertEqual(ni.key_phrase("Multi Commodity Exchange of India Limited"), "Multi Commodity")
        self.assertEqual(ni.key_phrase("Bank of Maharashtra"), "Bank of Maharashtra")
        self.assertEqual(ni.key_phrase("Larsen & Toubro Ltd."), "Larsen & Toubro")
        self.assertEqual(ni.key_phrase("Infosys Limited"), "Infosys")
        self.assertEqual(ni.key_phrase("The Federal Bank Limited"), "Federal Bank")  # not "The Federal"
        self.assertEqual(ni.key_phrase(None), "")

    def test_quote_pages_are_not_stories(self):
        for title in ("Laurus Labs Share Price - Live NSE: LAURUSLABS Stock Price & Chart",
                      "LAURUSLABS Stock Price and Chart - NSE:LAURUSLABS",
                      "Sona BLW Precision Trader Analysis | StockIQ", "BHEL Share Price",
                      "AUROPHARMA Share Price Today - Aurobindo Pharma on NSE/BSE"):
            self.assertTrue(ni.QUOTE_PAGE.search(title), title)
        for title in ("BHEL gets two POWERGRID orders",
                      "Paytm Share Price Rebounds Over 2% to Rs 1,770 After 8.68% Crash"):
            self.assertFalse(ni.QUOTE_PAGE.search(title), title)

    def test_headline_must_name_the_company(self):
        rx = ni.headline_names("MCX", "Multi Commodity Exchange of India Limited")
        self.assertTrue(rx.search("Multi Commodity Exchange of India down 2.33% on Wednesday"))
        self.assertTrue(rx.search("Why are MCX shares under pressure today?"))
        self.assertFalse(rx.search("Amaroq could become a self-funding multi-commodity miner"))
        self.assertFalse(rx.search("Gold, silver prices tumble as stronger dollar weighs"))

    def test_query(self):
        q = ni.gnews_query("MCX", "Multi Commodity Exchange of India Limited", 7)
        self.assertEqual(q, '"Multi Commodity" OR "MCX share" OR "MCX shares" when:7d')
        self.assertEqual(ni.gnews_query("RADICO", None, 0), '"RADICO share" OR "RADICO shares" when:1d')

    def test_name_override(self):
        self.assertEqual(ni.parse_names(['sunpharma=Sun Pharma']), {"SUNPHARMA": "Sun Pharma"})
        with self.assertRaises(SystemExit):
            ni.parse_names(["SUNPHARMA"])


class Feeds(unittest.TestCase):
    def test_google_news_items(self):
        items = ni.parse_gnews(raw("gnews-MCX.xml"), "MCX")
        self.assertEqual(len(items), 12)
        ubs = next(i for i in items if i["source"] == "CNBC TV18")
        self.assertEqual(ubs["title"], "MCX share price target raised by UBS backing strong volume growth")
        self.assertEqual(ubs["time"].isoformat(), "2026-11-19T04:06:09+00:00")
        self.assertTrue(ubs["link"].startswith("https://news.google.com/"))
        self.assertTrue(ubs["id"].startswith("gn:"))

    def test_chart_gives_the_company_name(self):
        m = news.parse_chart(raw("chart-MCX.NS.json"), "MCX.NS")
        self.assertEqual(m["name"], "Multi Commodity Exchange of India Limited")
        self.assertEqual((m["price"], m["prev_close"], m["pct"]), (3535.0, 3645.0, -3.02))

    def test_indian_topics(self):
        item = {"ticker": "BHEL", "kind": "headline", "title": "BHEL gets two POWERGRID orders", "summary": ""}
        ubs = dict(item, ticker="MCX", title="MCX share price target raised by UBS")
        margin = dict(item, ticker="MCX", title="SEBI's new margin rules for commodity derivatives")
        ni.news.tag([item, ubs, margin], {"BHEL": None, "MCX": None}, ni.KEYWORDS)
        self.assertEqual(item["tags"], ["deal"])
        self.assertEqual(ubs["tags"], ["analyst"])
        self.assertEqual(margin["tags"], ["regulatory"])


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state", "news_indian.json")
        none = os.path.join(self.tmp.name, "none.json")
        self.base = ["--offline", DIR, "--state", self.state, "--now", NOW, "--hours", "168",
                     "--watch", none, "--picks", none]

    def tearDown(self):
        self.tmp.cleanup()

    def test_prices_and_named_headlines_once(self):
        code, out, err = run(["--tickers", "MCX", "MAHABANK", "--per-stock", "20", "--json"] + self.base)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        moves = {m["ticker"]: m for m in data["moves"]}
        self.assertEqual(moves["MCX"]["pct"], -3.02)
        self.assertTrue(moves["MCX"]["moving"])
        self.assertFalse(moves["MAHABANK"]["moving"])
        titles = [i["title"] for i in data["items"]]
        self.assertIn("Bank of Maharashtra may issue $175 million in MTNs under RBI swap window", titles)
        self.assertNotIn("Amaroq could become a self-funding multi-commodity miner, Citi says", titles)
        self.assertTrue(any(n.startswith("left out") and "MCX" in n for n in data["notes"]))
        times = [i["time"] for i in data["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        code, out, _ = run(["--tickers", "MCX", "MAHABANK", "--per-stock", "20"] + self.base)
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", out)

    def test_text_is_in_india_time_with_the_filings_reminder(self):
        code, out, err = run(["--tickers", "MCX", "--dry-run"] + self.base)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"MCX\s+3,535\.00\s+-3\.02% vs previous close 3,645\.00 at 20 Nov 15:28 IST  MOVING")
        self.assertIn("2026-11-19 09:36 IST  MCX         CNBC TV18", out)  # 04:06 UTC
        self.assertIn("tags: analyst", out)
        self.assertIn("https://www.nseindia.com/get-quotes/equity?symbol=MCX", out)
        self.assertIn("Checked 2026-11-21 12:00 IST", out)
        self.assertIn("Not financial advice", out)
        self.assertFalse(os.path.exists(self.state))

    def test_per_stock_cap_leaves_the_rest_for_later(self):
        code, out, _ = run(["--tickers", "MAHABANK", "--per-stock", "2", "--json"] + self.base)
        data = json.loads(out)
        self.assertEqual(len(data["items"]), 2)
        self.assertTrue(any("older stor" in n for n in data["notes"]))
        code, out, _ = run(["--tickers", "MAHABANK", "--per-stock", "2", "--json"] + self.base)
        self.assertEqual(code, 0)  # the next two, not "nothing new"
        self.assertEqual(len(json.loads(out)["items"]), 2)

    def test_name_override_decides_what_counts_as_naming_the_company(self):
        code, out, _ = run(["--tickers", "MAHABANK", "--name", "MAHABANK=Mahabank Zzz", "--json",
                            "--dry-run"] + self.base)
        data = json.loads(out)
        # only the headline that carries the symbol itself is left
        self.assertEqual([i["title"] for i in data["items"]],
                         ["Bank of Maharashtra (NSEI:MAHABANK) Stock Forecast & Analyst Predictions"])
        self.assertTrue(any("MAHABANK" in n for n in data["notes"] if n.startswith("left out")))

    def test_stocks_come_from_the_swing_files(self):
        watch = os.path.join(self.tmp.name, "swing_watch.json")
        picks = os.path.join(self.tmp.name, "swing_picks.json")
        with open(watch, "w") as fh:
            json.dump({"positions": [{"symbol": "MCX", "name": "MULTI COMMODITY EXCHANGE"}]}, fh)
        with open(picks, "w") as fh:
            json.dump({"picks": [
                {"symbol": "MAHABANK", "setup": "momentum", "qty": 50},
                {"symbol": "SOLARINDS", "setup": "momentum", "qty": 0},
                {"symbol": "TCS", "setup": "pullback", "qty": 3}]}, fh)
        self.assertEqual(ni.watch_from_swing(watch, picks),
                         {"MCX": "MULTI COMMODITY EXCHANGE", "MAHABANK": None})

    def test_no_stocks_falls_back_to_market_headlines(self):
        with mock.patch.object(ni, "run_market", return_value=0) as market:
            code, _, err = run(self.base)
        self.assertEqual(code, 0)
        self.assertIn("showing market headlines", err)
        market.assert_called_once()

    def test_keywords_mean_market_mode(self):
        with mock.patch.object(ni, "run_market", return_value=0) as market:
            run(["--keywords", "rbi", "--limit", "3"])
        market.assert_called_once_with(["rbi"], 3, False)


if __name__ == "__main__":
    unittest.main()
