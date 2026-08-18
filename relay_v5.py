"""
relay_v5.py — WebSocket relay for the full 215-stock universe + NIFTY spot.
Fixes v4's "database is locked" issue: ticks now go through a queue to a
single dedicated writer thread, instead of each Breeze callback thread
writing to SQLite directly and colliding with each other.
"""
import logging
import sqlite3
import re
import time
import queue
import threading
from datetime import datetime
from dotenv import dotenv_values
from breeze_connect import BreezeConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENV_PATH = "/opt/smb-algo/.env"
TRADE_DB_PATH = "/opt/smb-algo-stocks/trade.db"
MARKET_DB_PATH = "/opt/smb-algo-stocks/market_data.db"

TOKEN_TO_TICKER = {}
CODES_TO_SUBSCRIBE = []
tick_queue = queue.Queue()

def get_breeze():
    env = dotenv_values(ENV_PATH)
    breeze = BreezeConnect(api_key=env.get("ACCOUNT1_API_KEY"))
    breeze.generate_session(api_secret=env.get("ACCOUNT1_API_SECRET"), session_token=env.get("ACCOUNT1_SESSION_TOKEN"))
    logger.info("Breeze session initialised")
    return breeze

def load_data():
    market_conn = sqlite3.connect(MARKET_DB_PATH)
    for token, ticker in market_conn.execute("SELECT token, nse_ticker FROM token_map"):
        TOKEN_TO_TICKER[token] = ticker
    market_conn.close()
    logger.info(f"Loaded {len(TOKEN_TO_TICKER)} token mappings")

    trade_conn = sqlite3.connect(TRADE_DB_PATH)
    for ticker, code in trade_conn.execute("SELECT nse_ticker, breeze_code FROM stock_master"):
        CODES_TO_SUBSCRIBE.append(code)
    trade_conn.close()
    logger.info(f"Loaded {len(CODES_TO_SUBSCRIBE)} breeze_codes to subscribe")

def writer_thread():
    """Single dedicated writer — owns the only SQLite connection, no contention."""
    conn = sqlite3.connect(MARKET_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # allows concurrent reads while this writes
    written = 0
    while True:
        ticker, ltp = tick_queue.get()
        if ticker is None:  # sentinel to stop
            break
        try:
            conn.execute(
                """INSERT OR REPLACE INTO live_ticks
                   (instrument_type, nse_ticker, strike, expiry, option_type, ltp, updated_at)
                   VALUES ('SPOT', ?, 0, '', '', ?, ?)""",
                (ticker, ltp, datetime.now().isoformat())
            )
            conn.commit()
            written += 1
            if written % 100 == 0:
                logger.info(f"Writer: {written} ticks written so far")
        except Exception as e:
            logger.error(f"Write failed for {ticker}: {e}")
    conn.close()

def on_ticks(ticks):
    ltp = ticks.get("last")
    symbol = ticks.get("symbol", "")
    if not ltp:
        return
    m = re.search(r"!(\d+)$", symbol)
    if not m:
        return
    token = m.group(1)
    if token == "26000":
        tick_queue.put(("NIFTY", ltp))
        return
    ticker = TOKEN_TO_TICKER.get(token)
    if ticker:
        tick_queue.put((ticker, ltp))
    else:
        logger.warning(f"Unmapped token: {token} (symbol={symbol})")

def main():
    load_data()

    t = threading.Thread(target=writer_thread, daemon=True)
    t.start()

    breeze = get_breeze()
    breeze.on_ticks = on_ticks
    breeze.ws_connect()
    logger.info("WebSocket connected. Subscribing to NIFTY + full stock universe...")

    breeze.subscribe_feeds(exchange_code="NSE", stock_code="NIFTY", product_type="cash", get_exchange_quotes=True, get_market_depth=False)
    logger.info("Subscribed: NIFTY")

    subscribed = 0
    for code in CODES_TO_SUBSCRIBE:
        try:
            breeze.subscribe_feeds(exchange_code="NSE", stock_code=code, product_type="cash", get_exchange_quotes=True, get_market_depth=False)
            subscribed += 1
            if subscribed % 25 == 0:
                logger.info(f"Subscribed {subscribed}/{len(CODES_TO_SUBSCRIBE)}...")
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Subscribe failed for {code}: {e}")

    logger.info(f"Done subscribing: {subscribed}/{len(CODES_TO_SUBSCRIBE)} stocks + NIFTY.")
    logger.info(f"Queue size: {tick_queue.qsize()} — waiting for ticks (Ctrl+C to stop)...")
    while True:
        time.sleep(2)
        logger.info(f"Queue size: {tick_queue.qsize()}")

if __name__ == "__main__":
    main()
