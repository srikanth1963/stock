"""
relay_v1.py — WebSocket connection test only, no cache writes yet.
Confirms a Breeze WebSocket session can connect and receive ticks,
independent of the three existing REST-based apps.
"""
import logging
from dotenv import dotenv_values
from breeze_connect import BreezeConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENV_PATH = "/opt/smb-algo/.env"

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

def on_ticks(ticks):
    logger.info(f"TICK: {ticks}")

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
