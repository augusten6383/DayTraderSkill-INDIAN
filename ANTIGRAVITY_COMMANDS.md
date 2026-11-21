# Jemo Trading Skill Commands in Google Antigravity AI

You do NOT need Claude or any paid subscription. You can run every trading skill right here in this chat with Google Antigravity!

---

### Commands You Can Ask in Chat:

1. **Scan Market Breakouts**:
   > *"Run trader-scanner for Indian market"*
   * Scans Nifty 50, Bank Nifty, Sensex, and liquid stocks for 20-day high breakouts and 20-DMA reclaims.

2. **Check Market News**:
   > *"Run trader-news"*
   * Pulls real-time Moneycontrol & Economic Times market reports and F&O headlines.

3. **Time Intraday Entry (09:15-09:30 ORB)**:
   > *"Run trader-entry for Nifty"*
   * Checks if the 5-minute candle broke out of the 15-minute opening range.

4. **Plan Stop Loss & Take Profit**:
   > *"Plan exit for Nifty entry 22600, stop 22520, target 22760"*
   * Calculates reward-to-risk and sets the 15:15 IST mandatory square-off time.

5. **Option Position & Lot Sizer**:
   > *"Size Bank Nifty call option: entry 180, stop 140, budget 50000, max loss 2000"*
   * Enforces exact Indian index lot sizes (NIFTY 65, BANK NIFTY 30, SENSEX 20 as of November 2026; read from `config_indian.json`).

6. **Simulate Odds (Time Machine)**:
   > *"Run timemachine for Nifty: entry 22600, stop 22520, target 22760"*
   * Runs 5,000 Monte Carlo replays using 75-bar Indian market sessions.

7. **Risk Gatekeeper**:
   > *"Check risk for 65 qty Nifty entry 125, stop 95"*
   * Verifies NSE market hours, maximum loss limits, and lot size constraints.

9. **Swing Stock Picker (days to weeks)**:
   > *"Run the swing stock screen and advise me"*
   * Follow `trader-swing/SKILL.md`: run `python trader-scanner/swing_indian.py picks --limit 20 --json`, recommend the basket only when its rule is graded SUPPORTED or MODEST, check news and results dates for each stock, then give the basket to buy at the open, emergency stops, sizes and the sell-by date. Say plainly when the right advice is to do nothing. Never places an order.

8. **Connect Zerodha Kite**:
   > *"Check my Kite profile and current INFY quote"*
   * Uses your locally authenticated Kite Connect session for account reads and guarded orders.

9. **Live Market Quotes & Clock**:
   > *"Check Indian market clock and quotes for Nifty and Bank Nifty"*
