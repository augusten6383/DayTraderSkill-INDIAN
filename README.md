# 🇮🇳 Jemo Trading Skill

An open-source trading toolkit for the **Indian stock market (NSE & BSE)**: market clock, scanners, position sizing, a risk gate, backtests that report results after costs, a swing stock picker, an emailed monitor, and a guarded Zerodha Kite Connect adapter.

It covers **NIFTY 50**, **BANK NIFTY**, **SENSEX** and the liquid NSE stocks that have futures. It works from the command line, with **Google Antigravity AI** and with **Claude Code**.

> **Read this first.** The tools here test their own rules on real price history, and most rules failed. See [What the testing found](#-what-the-testing-found). Nothing in this project promises a profit, and nothing here is financial advice.

---

## ✨ Features

- **Swing Stock Picker**: Screens about 200 liquid NSE stocks for candidates to hold roughly two weeks. Every run re-tests each rule on about three years of daily prices after costs and only recommends candidates from rules that held up.
- **Swing Basket Monitor**: Watches the chosen stocks and emails an HTML report with progress, health and any decision due. Can be scheduled to run several times a day.
- **Backtests After Costs**: Replays the intraday opening-range rule on 5-minute bars and the swing rules on daily bars, net of slippage and charges, and says plainly whether each made money.
- **Entry Watcher**: Signals the first completed 5-minute bar that closes outside the 09:15 to 09:30 opening range, up or down.
- **Index Option Lot Sizer**: Sizes orders in whole exchange lots. Lot sizes live in `config_indian.json` and are refreshed from Kite's public instruments list.
- **Risk Gatekeeper**: Blocks orders outside market hours, after 15:00 IST, over the per-trade or daily loss limit, over the daily trade count, in the wrong lot multiple, or with a stop on the wrong side of the entry.
- **Market Calendar**: NSE trading hours and the official holiday list, with a warning when a year's list has not been loaded.
- **Stock News and Market Headlines**: Google News headlines and the day's move for each NSE stock in your basket, plus Moneycontrol and Economic Times market headlines.
- **Telegram Alerts**: Optional scheduled bot for the market open, opening-range breaks and the square-off reminder.
- **Guarded Kite Orders**: Delivery (CNC) limit buys only, behind a risk check, an explicit approval and a typed confirmation.

---

## 🧪 What the testing found

These results were measured in November 2026. The swing grades are recomputed on every run and can change.

| Rule | Tested on | Result after costs | Verdict |
| :--- | :--- | :--- | :--- |
| Intraday opening-range breakout | Nifty and Bank Nifty, 2 years of 5-minute bars, 24 variants each | About zero before costs, -0.12R to -0.39R per trade after costs | No edge. Do not trade it. |
| Momentum leaders: top 10 affordable stocks by 12-month return (skipping the latest month), held 21 trading days, tested from every start day | 218 NSE F&O stocks, about 4 years | Basket +3.02% per 21 days, 1.33% better than holding every stock (0.79% to 2.39% depending on the start day), positive in both halves | Modest evidence |
| The same rule with only 3 or 5 stocks | Same | No better than holding every stock | No edge. Do not shrink the basket. |
| Pullback in an uptrend (2-day RSI below 10) | Same | About zero, worse than just holding | Failed |
| 20-day breakout on volume | Same | Negative, worse than just holding | Failed |
| 20-day average reclaim | Same | Slightly positive, worse than just holding | Unproven |

Things to keep in mind about the one rule that held up:

- **The edge is small.** About half of the individual trades lose. The advantage only shows across a basket over many periods.
- **It is graded as the basket you would buy.** The screener tests the top `swing_basket` stocks (10 by default) that one position can afford, bought at the next open with no buy limit. A stock that stays in the basket pays no new costs.
- **Costs use your position size.** 0.30% of price plus a flat depository charge per sale (`swing_flat_cost_inr`, about ₹15). On a ₹5,000 position that is about 0.61% per round trip. Check the flat charge against your own contract note.
- **It has no normal stop.** A 3x ATR stop removed the whole advantage. Risk is controlled by small equal positions and the 21-day exit. The screener prints a wide "emergency stop" for sizing only.
- **The basket's worst 21-day period was about -19%.**
- **The numbers are flattered.** The stock list is today's F&O list, so stocks dropped from it in the past are missing, and several rules were tried before this one was kept.
- **Options are not supported by any of this.** The backtests measure the underlying. A bought option also pays time decay and a wider spread.

---

## 🕒 Market Specifications

| Parameter | Indian Market Rule |
| :--- | :--- |
| **Timezone** | `Asia/Kolkata` (IST, UTC+5:30) |
| **Trading Hours** | `09:15` to `15:30` IST |
| **Intraday Square-Off** | `15:15` IST |
| **New Intraday Entries** | Blocked after `15:00` IST by the risk check |
| **Bars per Session** | 75 five-minute bars |
| **Index Lot Sizes** | NIFTY 65, BANK NIFTY 30, SENSEX 20 (November 2026; they change, so refresh them) |
| **Currency** | Indian Rupee (`₹` / INR) |

---

## 🚀 Quick Setup Guide

### 1. Clone the Repository
```bash
git clone https://github.com/jemo21/jemo-trading-skill.git
cd jemo-trading-skill
```

### 2. Install Dependencies
Requires Python 3.10+:
```bash
pip install -r requirements.txt
```

### 3. Create Your Settings File
Copy `settings.example.json` to `settings.json` (which git ignores) and fill in what you need:
```bash
cp settings.example.json settings.json
```

| Key | Used for | Needed when |
| :--- | :--- | :--- |
| `kite_api_key`, `kite_api_secret` | Zerodha Kite Connect | You want Kite data or orders |
| `email_to`, `smtp_user`, `smtp_password` | Emailed monitor reports | You want reports by email |
| `telegram_bot_token`, `telegram_chat_id` | Telegram alerts | You use the Telegram bot |
| `sec_user_agent` | The US earnings analyst (`trader-analyst`) | You read SEC filings; set it to your name and email |

Environment variables with the same names in capitals (`KITE_API_KEY`, `SMTP_PASSWORD`, `EMAIL_TO` and so on) override the file.

Your trading limits live in `config_indian.json`: `budget_inr`, `max_loss_per_trade_inr`, `max_daily_loss_inr` and `max_trades_per_day`. The swing screener also reads `swing_basket` (how many stocks to hold) and `swing_flat_cost_inr` (the flat charge per sale). A swing basket is bought on one day, so delivery orders use their own day limits, `swing_max_trades_per_day` and `swing_max_daily_loss_inr`; the intraday limits are not affected.

### 4. Log In to Kite (optional)
Set the redirect URL in the Kite developer console, then run this in your own terminal:
```bash
python trader-broker/kite.py login
python trader-broker/kite.py profile
```
Open the printed URL, sign in, and paste the `request_token` from the redirect into the hidden prompt. The session is saved under the ignored `trader/state/` folder together with the API key it belongs to. Tokens expire daily. Never paste credentials or tokens into a chat.

Historical candles need a Kite Connect plan that includes market data. Without Kite, the price tools fall back to Yahoo Finance.

### 5. Set Up Email (optional)
For a Gmail account:
1. Turn on 2-Step Verification at https://myaccount.google.com/signinoptions/two-step-verification.
2. Create an app password at https://myaccount.google.com/apppasswords.
3. Put the 16-letter password in `settings.json` as `smtp_password`, with your address as `email_to` and `smtp_user`.
4. Check it: `python trader-alerts/swing_monitor.py test-email`.

Other providers work too: set `smtp_host` and `smtp_port` (defaults are `smtp.gmail.com` and `587`).

---

## 📈 Swing Trading Workflow (days to weeks)

This is the part of the project with evidence behind it.

### 1. Find Candidates
```bash
python trader-scanner/swing_indian.py picks
python trader-scanner/swing_indian.py picks --limit 20 --budget 100000 --max-loss 2500
python trader-scanner/swing_indian.py picks --basket 15 --flat-cost 15.34
python trader-scanner/swing_indian.py backtest
python trader-scanner/swing_indian.py refresh
```
- `picks` lists today's basket with an emergency stop, share count, the buy date and the sell-by date. It also saves `trader/swing_picks.json`. Buy the whole basket at the open; there is no buy limit.
- `--basket` sets how many stocks to hold and `--flat-cost` the flat rupee charge per round trip. The defaults are `swing_basket` and `swing_flat_cost_inr` in `config_indian.json`. The grade always describes the basket size you asked for.
- `backtest` prints how every rule has performed after costs, including each half of the period and each year.
- Only candidates from rules graded **SUPPORTED** or **MODEST** are recommended. When no rule has that grade, the right advice is to do nothing.
- The first run of a day downloads daily prices and takes about two minutes.

### 2. Monitor the Basket and Get It by Email
```bash
python trader-alerts/swing_monitor.py init --top 10 --until 2026-12-14
python trader-alerts/swing_monitor.py run
python trader-alerts/swing_monitor.py run --no-email
```
- `init` starts watching the top picks from the latest screen and writes `trader/swing_watch.json`. Use `--force` to replace an existing list.
- `run` builds the report, saves it under `trader/reports/` and emails it. It does nothing on weekends, holidays or after the `--until` date.

Each report contains:
- **Decisions for you**: do not chase, watch, exit, exit tomorrow, sell today, or hold.
- **Basket progress**: profit or loss, Nifty over the same days, stocks up and down.
- **A row per stock**: last price, today's move, change since the buy, profit or loss, performance against Nifty, distance above the emergency stop.
- **Progress and health**: day of the plan, days left, price range since the buy, position against the 20-day and 50-day averages, and momentum rank now versus when picked.

Profit and loss assumes the planned quantity at the buy-day open. Record your real fills in `trader/swing_watch.json` as `actual_entry` and `actual_qty`; set `actual_qty` to `0` for a stock you skipped.

### 3. Schedule It
The monitor is safe to run on a timer because it skips non-trading days by itself.

**Windows (PowerShell)**, three runs a day:
```powershell
$root = "C:\path\to\jemo-trading-skill"
$py = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$root\trader-alerts\swing_monitor.py`" run" -WorkingDirectory $root
$triggers = "09:40","13:00","15:45" | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-ScheduledTask -TaskName "SwingBasketMonitor" -Action $action -Trigger $triggers
```
Remove it with `Unregister-ScheduledTask SwingBasketMonitor`. The PC must be on and you must be logged in at those times.

**Linux or macOS (cron)**, with the machine clock on IST:
```
40 9,13 * * 1-5  cd /path/to/jemo-trading-skill && python trader-alerts/swing_monitor.py run
45 15 * * 1-5    cd /path/to/jemo-trading-skill && python trader-alerts/swing_monitor.py run
```

---

## 🛠️ Other Tools

### Market Clock and Quotes
```bash
python trader-alerts/alerts_indian.py clock
python trader-alerts/alerts_indian.py quote NIFTY BANKNIFTY RELIANCE
```

### Daily Setup Scanner
```bash
python trader-scanner/scan_indian.py
```
*Lists 20-day breakouts and 20-day average reclaims on the indices and a short list of large stocks. Both setups failed or were unproven in the swing backtest, so treat the output as a watchlist, not a signal.*

### Intraday Entry Watcher
```bash
python trader-entry/entry_indian.py ^NSEI
python trader-entry/entry_indian.py ^NSEBANK --direction long --json
```
*Reports WAITING, TRIGGERED, NO_DATA or MARKET_CLOSED for the opening-range rule. It only counts completed bars and needs all three opening-range bars.*

### Backtest the Opening-Range Rule
```bash
python trader-timemachine/backtest_indian.py --symbol ^NSEI
python trader-timemachine/backtest_indian.py --symbol ^NSEBANK --stop range --rr 2 --last-entry 15:00
python trader-timemachine/backtest_indian.py --source kite --symbol NIFTY --days 730
python trader-timemachine/backtest_indian.py --source csv --csv bars.csv
```
*Replays exactly the rule the entry watcher signals. Yahoo covers about 60 sessions; Kite or a CSV (`datetime, open, high, low, close`) covers more. Set `--cost-pct` and `--slippage-pct` from your own contract notes.*

### Exit Planner
```bash
python trader-exit/exit_indian.py --symbol NIFTY --entry 22600 --or-high 22620 --or-low 22540 --rr 1.5
```

### Option Lot Sizer
```bash
python trader-budget/size_indian.py --symbol BANKNIFTY --entry 125 --stop 95 --budget 50000 --max-loss 2000
```
*Rounds down to whole lots and refuses a stop at or above the entry.*

### Risk Check
```bash
python trader-risk/check_indian.py --symbol NIFTY --qty 65 --entry 125 --stop 95
python trader-risk/check_indian.py --symbol INFY --qty 10 --entry 1500 --stop 1450 --realized-loss 1200 --trades 1
```

### News and Institutional Flow Headlines
```bash
python trader-news/news_indian.py
python trader-news/news_indian.py --tickers MCX BHEL --hours 168
python trader-news/news_indian.py --keywords nifty "bank nifty" --limit 10
python trader-pelosi/fii_dii.py
```
*With no arguments the news tool checks the swing basket: each stock's move against the previous close and the Google News headlines that name the company, shown once, in IST. `--keywords` or `--market` reads the Moneycontrol and Economic Times market feeds instead. Exchange filings (results dates, block deals, pledges) are not read, because NSE and BSE refuse automated requests. The FII/DII tool finds headlines that mention the flows; it does not download the official figures.*

### Time Machine
```bash
python trader-timemachine/timemachine_indian.py --entry 22600 --stop 22520 --target 22760 --runs 5000
```
*A random walk with an assumed volatility, not market history. It cannot tell a good setup from a bad one; use the backtests instead.*

### Keep Lot Sizes and Holidays Current
```bash
python indian_instruments.py refresh
python market_calendar_indian.py import nse-holidays-2027.json
```
*The first reads current index lot sizes from Kite's public instruments list (no login needed). The second loads the list NSE publishes each December: save the JSON from `https://www.nseindia.com/api/holiday-master?type=trading` in your browser, then import it. Until a year's list is loaded, the clock warns that it cannot confirm holidays. The 2026 list is built in.*

---

## 🏦 Zerodha Kite Connect

Kite has no paper account: orders use real money.

```bash
python trader-broker/kite.py profile
python trader-broker/kite.py quote --symbol INFY
python trader-broker/kite.py holdings
python trader-broker/kite.py positions
python trader-broker/kite.py orders
```

Placing an order takes three separate steps for one order file (`trader/orders.json`):
```bash
python trader-broker/kite.py check
python trader-broker/kite.py approve --reply "yes"
python trader-broker/kite.py place
```
1. **check** runs the Indian risk check on the exact order.
2. **approve** records your explicit yes for that order.
3. **place** asks you to type a confirmation containing the order's fingerprint in an interactive terminal. It cannot run from a scheduler.

Limits of the adapter:
- Only NSE/BSE delivery (CNC) limit buys. No options, no intraday (MIS) products, no automated selling.
- The planned stop is used by the risk check but is **not** attached to the order. Place a GTT stop in Kite yourself, or watch it.
- Untracked orders in the Kite account block the risk check until reconciled.
- If a session is rejected, the tool prints a one-line message telling you to log in again.

---

## 📣 Telegram Alerts (optional)

`telegram_bot/cron_runner.py` sends a market-open message, opening-range break alerts for Nifty and Bank Nifty, and a square-off reminder. `.github/workflows/trader_cron.yml` runs it on GitHub Actions every 15 minutes during the session.

- Repository secrets needed: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and for the market-open quotes `KITE_API_KEY` and a current `KITE_ACCESS_TOKEN` (it expires daily).
- Break alerts use Yahoo data, give index levels only, and are sent only while a break is fresh.
- The opening-range rule showed no edge in testing. Treat these alerts as information, not trade signals.

Test delivery with `python telegram_bot/notifier.py test`.

---

## 🤖 Using with AI Assistants

### With Claude Code
Open this folder in Claude Code. Each skill lives once, in its `trader-*` folder at the project root. To make the slash commands find them, run this once after cloning (and again after adding a skill folder):

```
powershell -ExecutionPolicy Bypass -File link_skills.ps1
```

It puts a folder link under `.claude/skills/` for every skill, pointing back at the root folder, so there are no copies to keep in step. The links are not stored in git. The swing picker is then available as a slash command:

```
/trader-swing
```

It runs the screen, drops rules without evidence, checks news and results dates for the basket, and gives the basket to buy at the open, sizes and a sell-by date. It says so when the right answer is to do nothing, and it never places an order. Its instructions are in `trader-swing/SKILL.md`.

The other `trader-*` folders are skills too (`/trader-scanner`, `/trader-news`, `/trader-budget`, `/trader-risk`, `/trader-broker` and so on). Their `SKILL.md` files were written for the US market, so for Indian work prefer the `*_indian.py` commands in this README.

### With Google Antigravity AI
Open the repository and ask in plain language. `ANTIGRAVITY_COMMANDS.md` lists the prompts, for example:
- *"Run the swing stock screen and advise me"*
- *"Is the Indian market open?"*
- *"Size a Bank Nifty call: entry 180, stop 140, max loss 2000"*
- *"Check risk for 65 qty Nifty entry 125, stop 95"*

---

## 📊 Data Sources and Their Limits

| Source | Used for | Limits |
| :--- | :--- | :--- |
| Kite Connect | Daily and 5-minute history, account data, orders | Needs a daily login; history needs a plan with market data |
| Kite public instruments list | Lot sizes, the F&O stock list | No login needed |
| Yahoo Finance | Fallback prices, monitor reports, entry watcher, Telegram alerts | Can lag the exchange by a few minutes; about 60 sessions of 5-minute bars |
| Moneycontrol and Economic Times RSS | News headlines | Recent general headlines only |
| NSE holiday list | Market calendar | Imported by hand once a year |

---

## 🧱 Project Layout

| Path | Contents |
| :--- | :--- |
| `trader-scanner/` | `swing_indian.py` (swing picker and its backtest), `scan_indian.py` |
| `trader-alerts/` | `swing_monitor.py` (emailed monitor), `alerts_indian.py` (clock and quotes) |
| `trader-timemachine/` | `backtest_indian.py` (opening-range backtest), `timemachine_indian.py` |
| `trader-entry/`, `trader-exit/` | Intraday entry watcher and exit planner |
| `trader-budget/`, `trader-risk/` | Lot sizer and risk gatekeeper |
| `trader-broker/` | `kite.py` (guarded Kite adapter) |
| `trader-news/`, `trader-pelosi/` | News and FII/DII headlines |
| `telegram_bot/` | Telegram notifier and scheduled runner |
| `market_calendar_indian.py`, `indian_instruments.py` | Calendar, holidays, index lot sizes |
| `config_indian.json` | Your limits and the index lot sizes |
| `trader/` | Generated files: picks, watch list, reports, cached prices, Kite session (all ignored by git) |
| `tests/` | Unit tests |

The `*.py` files without `_indian` in their name, and `trader-analyst/`, come from the original US-market project.

---

## ✅ Tests

```bash
cd tests
python -m unittest test_indian test_kite test_swing test_swing_monitor
python -m unittest discover -p "test_*.py"
```

The first command covers the Indian tools. In the full run, two tests in `test_repo.py` fail: they check the original US project's README wording and folder layout, which this fork changed.

---

## 🔒 Security & Privacy Notice

- **No automatic orders.** Every live order needs your explicit approval and a typed confirmation in a terminal.
- **Keep secrets local.** `settings.json`, the `trader/` folder and logs are ignored by git. Never commit API keys, access tokens or app passwords, and never paste them into a chat.
- **Use an app password for email**, not your account password.
- **Live trading risk.** Kite orders use real money. The checks here reduce mistakes; they do not remove trading risk, and a stock can gap through any stop.
- **Not financial advice.** Backtests describe the past. They do not guarantee future results.

---

## 📄 License

This project is licensed under the **MIT License**: you are free to modify, distribute, and use it in commercial or personal projects. See [LICENSE](LICENSE) for details.
