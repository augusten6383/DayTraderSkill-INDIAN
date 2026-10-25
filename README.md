# 🇮🇳 Indian Market Day Trader Skill

An open-source, AI-powered day trading and index options suite built for the **Indian Stock Market (NSE & BSE)**. 

Supports **NIFTY 50**, **BANK NIFTY**, and **SENSEX** options and equities, integrated directly with **Angel One SmartAPI**.

Works out-of-the-box with **Google Antigravity AI** (no paid subscription needed) and **Claude Code** (via skill standards).

---

## ✨ Features

- **Voice & Chat Native**: Look up spot prices, ATM strikes, and Call/Put option premiums in plain English.
- **Automated 2FA (TOTP)**: No more waiting for SMS OTPs — generates rolling TOTP codes automatically using `pyotp`.
- **Chart Breakout Scanner**: Identifies 20-day high breakouts, 20-DMA reclaims, and Opening Range Breakouts (ORB) on 5-minute candles.
- **Index Options Lot Sizer**: Sizes orders strictly by exchange lot rules:
  - **NIFTY 50**: 25 qty / lot
  - **BANK NIFTY**: 15 qty / lot
  - **SENSEX**: 10 qty / lot
- **Time Machine (Monte Carlo)**: Replays 5,000+ intraday simulations calibrated for the **75-bar** Indian market session (09:15 to 15:30 IST).
- **Mandatory Risk Gatekeeper**: Enforces max daily loss, trade loss caps, and a hard square-off cutoff at **15:15 IST**.
- **Real-Time News**: Scrapes live financial headlines and F&O reports directly from **Moneycontrol** and **The Economic Times**.
- **FII / DII Flow Tracker**: Monitors institutional capital flows in cash and derivatives.
- **SmartAPI Order Ticket Generator**: Builds valid Angel One `placeOrder` JSON tickets ready for execution.

---

## 🕒 Market Specifications

| Parameter | Indian Market Rule |
| :--- | :--- |
| **Timezone** | `Asia/Kolkata` (IST, UTC+5:30) |
| **Trading Hours** | `09:15 AM` to `03:30 PM IST` |
| **Intraday Square-Off** | `15:15 IST` (enforced across all exit tools) |
| **Bars per Session** | **75 bars** (5-minute intervals) |
| **Currency** | Indian Rupee (`₹` / INR) |

---

## 🚀 Quick Setup Guide

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/day-trader-skill.git
cd day-trader-skill
```

### 2. Install Dependencies
Requires Python 3.10+ (Standard library + SmartAPI packages):
```bash
pip install smartapi-python pyotp requests pandas logzero websocket-client
```

### 3. Add Your Angel One Credentials
Copy `settings.example.json` to `settings.json`:
```bash
cp settings.example.json settings.json
```
Edit `settings.json`:
```json
{
  "api_key": "YOUR_SMARTAPI_KEY",
  "client_id": "YOUR_CLIENT_ID",
  "pin": "YOUR_4_DIGIT_MPIN",
  "totp_secret": "YOUR_BASE32_TOTP_SECRET"
}
```
*(Your `settings.json` is automatically ignored by `.gitignore` so your private keys are never exposed on GitHub).*

---

## 🧪 Testing Your Connection

Verify your Angel One connection and live quotes with one command:
```bash
python test_angel_one.py
```
Expected output:
```text
Connecting to Angel One SmartAPI with Client ID: ...
Generated dynamic TOTP: 123456
✅ Login Successful!

--- Live Index Quotes ---
📈 NIFTY 50 (NSE):   ₹22,600.00
📈 BANK NIFTY (NSE): ₹54,287.35
📈 SENSEX (BSE):     ₹73,123.83
```

---

## 🛠️ Tool Suite & CLI Commands

You can run any tool individually from your terminal or ask your AI assistant:

### 1. Market Clock & Status
```bash
python trader-alerts/alerts_indian.py clock
```
*Displays whether NSE/BSE is open, current IST time, and countdown to next session.*

### 2. Chart Breakout Scanner
```bash
python trader-scanner/scan_indian.py
```
*Scans Nifty, Bank Nifty, and top F&O heavyweights for daily breakout setups.*

### 3. Option Lot & Risk Sizer
```bash
python trader-budget/size_indian.py --symbol NIFTY --entry 125 --stop 95 --budget 50000 --max-loss 2000
```
*Calculates exact lot size rounded down to exchange multiples.*

### 4. Live Financial News
```bash
python trader-news/news_indian.py --keywords nifty "bank nifty"
```
*Fetches top headlines from Moneycontrol and The Economic Times.*

### 5. Time Machine Replay
```bash
python trader-timemachine/timemachine_indian.py --entry 22600 --stop 22520 --target 22760 --runs 5000
```
*Simulates 5,000 outcomes based on 75 five-minute bars per session.*

### 6. Risk Check & Gatekeeper
```bash
python trader-risk/check_indian.py --symbol NIFTY --qty 50 --entry 125 --stop 95
```
*Validates that the trade complies with daily loss limits and market trading hours.*

### 7. Angel One Order Ticket
```bash
python trader-broker/angel_ticket.py --symbol NIFTY24OCT2424500CE --token 99926000 --side BUY --lots 2
```
*Generates the JSON payload for SmartAPI order execution.*

---

## 🤖 Using with AI Assistants

### With Google Antigravity AI (Free / Default)
1. Open this repository in Google Antigravity.
2. The skills are automatically discovered under `trader-*`.
3. Simply talk to the assistant:
   - *"Scan today's Indian market breakouts"*
   - *"Size an ATM Call on Bank Nifty with ₹2,000 risk"*
   - *"What's the latest Nifty news?"*

### With Claude Code
Install the skills folder into your `.claude/skills/` directory:
```bash
mkdir -p ~/.claude/skills
cp -r trader-* ~/.claude/skills/
```
In Claude Code, you can trigger them via slash commands:
`/trader-scanner`, `/trader-news`, `/trader-budget`, `/trader-risk`, `/trader-broker`.

---

## 🔒 Security & Privacy Notice

- **Safety First**: This project never places real orders automatically without explicit user confirmation.
- **Credentials Protection**: Never commit your `settings.json`, API keys, or TOTP secrets to any public repository.
- **Paper Trading**: Test all strategies and sizing algorithms using paper trading before putting real capital at risk.

---

## 📄 License

This project is licensed under the **MIT License** — you are free to modify, distribute, and use it in commercial or personal projects. See [LICENSE](LICENSE) for details.
