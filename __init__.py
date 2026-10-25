from mycroft import MycroftSkill, intent_handler
import pyotp
import requests
import json
import os
from datetime import datetime

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None


class DayTraderSkill(MycroftSkill):
    def __init__(self):
        super(DayTraderSkill, self).__init__(name="DayTraderSkill")
        self.smart_api = None
        self.jwt_token = None
        self.feed_token = None
        self.indices = {
            "nifty": {
                "name": "NIFTY 50",
                "symbol": "Nifty 50",
                "exchange": "NSE",
                "token": "99926000",
                "strike_step": 50,
                "opt_symbol": "NIFTY",
                "opt_exchange": "NFO"
            },
            "bank nifty": {
                "name": "BANK NIFTY",
                "symbol": "Nifty Bank",
                "exchange": "NSE",
                "token": "99926009",
                "strike_step": 100,
                "opt_symbol": "BANKNIFTY",
                "opt_exchange": "NFO"
            },
            "sensex": {
                "name": "SENSEX",
                "symbol": "SENSEX",
                "exchange": "BSE",
                "token": "99919000",
                "strike_step": 100,
                "opt_symbol": "SENSEX",
                "opt_exchange": "BFO"
            }
        }

    def initialize(self):
        self.log.info("Indian Index Options Day Trader Skill Initialized")

    def _login(self):
        """Authenticates with Angel One SmartAPI using credentials & dynamic TOTP"""
        api_key = self.settings.get("api_key")
        client_id = self.settings.get("client_id")
        pin = self.settings.get("pin")
        totp_secret = self.settings.get("totp_secret")

        if not all([api_key, client_id, pin, totp_secret]):
            self.log.error("Missing Angel One credentials in settings.")
            return False

        if SmartConnect is None:
            self.log.error("SmartApi package is not installed.")
            return False

        try:
            self.smart_api = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()
            session = self.smart_api.generateSession(client_id, pin, totp)
            
            if session and session.get("status"):
                self.jwt_token = session["data"]["jwtToken"]
                self.feed_token = self.smart_api.getfeedToken()
                self.log.info("Angel One SmartAPI login successful!")
                return True
            else:
                self.log.error(f"Angel One login failed: {session.get('message')}")
                return False
        except Exception as e:
            self.log.error(f"Exception during SmartAPI login: {str(e)}")
            return False

    def ensure_authenticated(self):
        """Ensures active session or re-authenticates"""
        if not self.smart_api or not self.jwt_token:
            return self._login()
        return True

    def get_index_spot(self, index_key):
        """Fetches current LTP for the requested Index (Nifty, Bank Nifty, Sensex)"""
        if not self.ensure_authenticated():
            return None

        info = self.indices.get(index_key.lower().strip())
        if not info:
            return None

        try:
            res = self.smart_api.ltpData(
                info["exchange"],
                info["symbol"],
                info["token"]
            )
            if res and res.get("status") and "data" in res:
                return float(res["data"]["ltp"])
        except Exception as e:
            self.log.error(f"Error fetching index LTP: {e}")
        return None

    def calculate_atm_strike(self, spot_price, strike_step):
        """Calculates nearest At-The-Money (ATM) strike"""
        return round(spot_price / strike_step) * strike_step

    def search_option_contract(self, opt_exchange, opt_symbol, strike, opt_type):
        """Searches scrip master or uses searchScrip API for specific strike CE/PE"""
        if not self.ensure_authenticated():
            return None

        try:
            search_str = f"{opt_symbol}{int(strike)}{opt_type.upper()}"
            res = self.smart_api.searchScrip(exchange=opt_exchange, searchscrip=search_str)
            if res and res.get("status") and res.get("data"):
                # Pick the nearest active contract from search results
                first_match = res["data"][0]
                return {
                    "symbol": first_match.get("tradingsymbol"),
                    "token": first_match.get("symboltoken")
                }
        except Exception as e:
            self.log.error(f"Error searching option contract: {e}")
        return None

    def get_option_ltp(self, opt_exchange, symbol, token):
        """Fetches LTP of an option contract"""
        if not self.ensure_authenticated():
            return None
        try:
            res = self.smart_api.ltpData(opt_exchange, symbol, token)
            if res and res.get("status") and "data" in res:
                return float(res["data"]["ltp"])
        except Exception as e:
            self.log.error(f"Error getting option LTP: {e}")
        return None

    @intent_handler("day.trader.intent")
    def handle_day_trader(self, message):
        self.speak_dialog("welcome")

    @intent_handler("index.spot.intent")
    def handle_index_spot(self, message):
        raw_index = message.data.get("index", "").lower().strip()
        
        index_key = None
        if "bank" in raw_index:
            index_key = "bank nifty"
        elif "sensex" in raw_index:
            index_key = "sensex"
        elif "nifty" in raw_index:
            index_key = "nifty"

        if not index_key:
            self.speak_dialog("not.found", {"item": raw_index})
            return

        idx_info = self.indices[index_key]
        self.speak_dialog("looking.up", {"item": idx_info["name"]})

        spot = self.get_index_spot(index_key)
        if spot is not None:
            atm = self.calculate_atm_strike(spot, idx_info["strike_step"])
            self.speak_dialog("index.price", {
                "index": idx_info["name"],
                "price": f"{spot:,.2f}",
                "atm": str(atm)
            })
            if hasattr(self, "gui"):
                self.gui["index_name"] = idx_info["name"]
                self.gui["spot_price"] = f"{spot:,.2f}"
                self.gui["atm_strike"] = str(atm)
                self.gui.show_page("day_trader_skill.qml")
        else:
            self.speak_dialog("error")

    @intent_handler("option.price.intent")
    def handle_option_price(self, message):
        raw_index = message.data.get("index", "").lower().strip()
        opt_type = message.data.get("opttype", "call").lower().strip()
        opt_code = "CE" if "call" in opt_type or "ce" in opt_type else "PE"

        index_key = None
        if "bank" in raw_index:
            index_key = "bank nifty"
        elif "sensex" in raw_index:
            index_key = "sensex"
        elif "nifty" in raw_index:
            index_key = "nifty"

        if not index_key:
            self.speak_dialog("not.found", {"item": raw_index})
            return

        idx_info = self.indices[index_key]
        spot = self.get_index_spot(index_key)
        if spot is None:
            self.speak_dialog("error")
            return

        # Determine strike: either specified by user or default to ATM
        user_strike = message.data.get("strike")
        if user_strike:
            try:
                strike = int(float(user_strike))
            except ValueError:
                strike = self.calculate_atm_strike(spot, idx_info["strike_step"])
        else:
            strike = self.calculate_atm_strike(spot, idx_info["strike_step"])

        self.speak_dialog("looking.up", {"item": f"{idx_info['name']} {strike} {opt_code}"})

        contract = self.search_option_contract(
            idx_info["opt_exchange"],
            idx_info["opt_symbol"],
            strike,
            opt_code
        )

        if contract and contract.get("token"):
            ltp = self.get_option_ltp(
                idx_info["opt_exchange"],
                contract["symbol"],
                contract["token"]
            )
            if ltp is not None:
                self.speak_dialog("option.price", {
                    "contract": contract["symbol"],
                    "price": f"{ltp:,.2f}"
                })
                if hasattr(self, "gui"):
                    self.gui["index_name"] = contract["symbol"]
                    self.gui["spot_price"] = f"₹{ltp:,.2f}"
                    self.gui.show_page("day_trader_skill.qml")
                return

        self.speak_dialog("error")


def create_skill():
    return DayTraderSkill()
