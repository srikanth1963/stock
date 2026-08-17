"""
relay_v3.py — WebSocket relay for the full 215-stock universe + NIFTY spot.
Writes every tick to market_data.db's live_ticks cache table.
"""
import logging
import sqlite3
import time
from datetime import datetime
from dotenv import dotenv_values
from breeze_connect import BreezeConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENV_PATH = "/opt/smb-algo/.env"
TRADE_DB_PATH = "/opt/smb-algo-stocks/trade.db"
MARKET_DB_PATH = "/opt/smb-algo-stocks/market_data.db"

# breeze_code -> nse_ticker, built at startup from stock_master
CODE_TO_TICKER = {}

def get_breeze():
    env = dotenv_values(ENV_PATH)
    api_key = env.get("ACCOUNT1_API_KEY")
    api_secret = env.get("ACCOUNT1_API_SECRET")
    session_token = env.get("ACCOUNT1_SESSION_TOKEN")
    if not all([api_key, api_secret, session_token]):
        raise RuntimeError("Missing Breeze credentials in .env")
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    logger.info("Breeze session initialised")
    return breeze

def load_universe():
    conn = sqlite3.connect(TRADE_DB_PATH)
    rows = conn.execute("SELECT nse_ticker, breeze_code FROM stock_master").fetchall()
    conn.close()
    for ticker, code in rows:
        CODE_TO_TICKER[code] = ticker
    logger.info(f"Loaded {len(CODE_TO_TICKER)} stocks from stock_master")

def write_tick(ticker, ltp):
    conn = sqlite3.connect(MARKET_DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO live_ticks
           (instrument_type, nse_ticker, strike, expiry, option_type, ltp, updated_at)
           VALUES ('SPOT', ?, 0, '', '', ?, ?)""",
        (ticker, ltp, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def on_ticks(ticks):
    stock_name = ticks.get("stock_name", "")
    ltp = ticks.get("last")
    if not ltp:
        return
    if stock_name == "NIFTY 50":
        write_tick("NIFTY", ltp)
        return
    ticker = CODE_TO_TICKER.get(stock_name)
    if ticker:
        write_tick(ticker, ltp)
    else:
        logger.warning(f"Unmapped tick: stock_name={stock_name}")

def main():
    load_universe()
    breeze = get_breeze()
    breeze.on_ticks = on_ticks
    breeze.ws_connect()
    logger.info("WebSocket connected. Subscribing to NIFTY + full stock universe...")

    breeze.subscribe_feeds(
        exchange_code="NSE", stock_code="NIFTY",
        product_type="cash", get_exchange_quotes=True, get_market_depth=False
    )
    logger.info("Subscribed: NIFTY")

    subscribed = 0
    for code in CODE_TO_TICKER:
        try:
            breeze.subscribe_feeds(
                exchange_code="NSE", stock_code=code,
                product_type="cash", get_exchange_quotes=True, get_market_depth=False
            )
            subscribed += 1
            if subscribed % 25 == 0:
                logger.info(f"Subscribed {subscribed}/{len(CODE_TO_TICKER)}...")
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Subscribe failed for {code}: {e}")

    logger.info(f"Done subscribing: {subscribed}/{len(CODE_TO_TICKER)} stocks + NIFTY.")
    logger.info("Waiting for ticks (Ctrl+C to stop)...")
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
