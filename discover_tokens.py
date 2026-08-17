"""
discover_tokens.py — One-time discovery: maps Breeze's numeric exchange tokens
to nse_ticker by subscribing one stock at a time and capturing its first tick.
Run once; result is stored in market_data.db's token_map table.
"""
import logging
import sqlite3
import time
import re
from dotenv import dotenv_values
from breeze_connect import BreezeConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENV_PATH = "/opt/smb-algo/.env"
TRADE_DB_PATH = "/opt/smb-algo-stocks/trade.db"
MARKET_DB_PATH = "/opt/smb-algo-stocks/market_data.db"

_last_token = {"value": None}

def get_breeze():
    env = dotenv_values(ENV_PATH)
    breeze = BreezeConnect(api_key=env.get("ACCOUNT1_API_KEY"))
    breeze.generate_session(api_secret=env.get("ACCOUNT1_API_SECRET"), session_token=env.get("ACCOUNT1_SESSION_TOKEN"))
    logger.info("Breeze session initialised")
    return breeze

def on_ticks(ticks):
    symbol = ticks.get("symbol", "")
    m = re.search(r"!(\d+)$", symbol)
    if m:
        _last_token["value"] = m.group(1)

def save_mapping(conn, token, ticker):
    conn.execute("INSERT OR REPLACE INTO token_map (token, nse_ticker) VALUES (?, ?)", (token, ticker))
    conn.commit()

def main():
    trade_conn = sqlite3.connect(TRADE_DB_PATH)
    rows = trade_conn.execute("SELECT nse_ticker, breeze_code FROM stock_master").fetchall()
    trade_conn.close()
    logger.info(f"Discovering tokens for {len(rows)} stocks...")

    market_conn = sqlite3.connect(MARKET_DB_PATH)

    breeze = get_breeze()
    breeze.on_ticks = on_ticks
    breeze.ws_connect()

    found = 0
    missed = []
    for i, (ticker, code) in enumerate(rows, 1):
        _last_token["value"] = None
        try:
            breeze.subscribe_feeds(exchange_code="NSE", stock_code=code, product_type="cash", get_exchange_quotes=True, get_market_depth=False)
            time.sleep(1.5)
            if _last_token["value"]:
                save_mapping(market_conn, _last_token["value"], ticker)
                found += 1
            else:
                missed.append(ticker)
                logger.warning(f"No tick received for {ticker} ({code})")
            breeze.unsubscribe_feeds(exchange_code="NSE", stock_code=code, product_type="cash", get_exchange_quotes=True, get_market_depth=False)
        except Exception as e:
            missed.append(ticker)
            logger.error(f"Failed for {ticker} ({code}): {e}")
        if i % 25 == 0:
            logger.info(f"Progress: {i}/{len(rows)} — {found} mapped so far")

    market_conn.close()
    logger.info(f"Done. Mapped: {found}/{len(rows)}. Missed: {missed}")

if __name__ == "__main__":
    main()
