"""
relay_v2.py — WebSocket relay writing live ticks to market_data.db cache.
Simple per-tick write (no batching) — revisit if write volume becomes an issue
once scaled beyond a single test feed.
"""
import logging
import sqlite3
from datetime import datetime
from dotenv import dotenv_values
from breeze_connect import BreezeConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENV_PATH = "/opt/smb-algo/.env"
DB_PATH = "/opt/smb-algo-stocks/market_data.db"

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

def write_tick(ticker, ltp):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO live_ticks
           (instrument_type, nse_ticker, strike, expiry, option_type, ltp, updated_at)
           VALUES ('SPOT', ?, 0, '', '', ?, ?)""",
        (ticker, ltp, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def on_ticks(ticks):
    ltp = ticks.get("last")
    if ltp:
        write_tick("NIFTY", ltp)
        logger.info(f"Wrote tick: NIFTY @ {ltp}")

def main():
    breeze = get_breeze()
    breeze.on_ticks = on_ticks
    breeze.ws_connect()
    logger.info("WebSocket connected, subscribing to NIFTY spot...")
    breeze.subscribe_feeds(
        exchange_code="NSE",
        stock_code="NIFTY",
        product_type="cash",
        get_exchange_quotes=True,
        get_market_depth=False
    )
    logger.info("Subscribed. Waiting for ticks (Ctrl+C to stop)...")
    import time
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
