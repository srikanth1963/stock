"""
SMB Algo — Breeze API Client
Wraps the breeze-connect SDK.
Handles: LTP fetching, order placement, order status polling.
In paper mode: returns simulated LTP, skips actual orders.
"""

import logging
import asyncio
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Breeze connection pool — one per account (keyed by account name)
_connections: dict = {}


def get_breeze(account: dict):
    """
    Returns a connected BreezeConnect instance for the given account.
    Creates and caches the connection if it doesn't exist.
    """
    name = account["name"]
    if name not in _connections:
        try:
            from breeze_connect import BreezeConnect
            from core.accounts import get_session_token

            breeze = BreezeConnect(api_key=account["api_key"])
            token = get_session_token(name)
            if not token:
                logger.warning(f"[{name}] No session token — Breeze not connected")
                return None
            breeze.generate_session(
                api_secret=account["api_secret"],
                session_token=token
            )
            _connections[name] = breeze
            logger.info(f"[{name}] Breeze session established")
        except Exception as e:
            logger.error(f"[{name}] Breeze connection failed: {e}")
            return None
    return _connections[name]


def clear_connection(account_name: str):
    """Clear cached connection (called after session token refresh)."""
    _connections.pop(account_name, None)


async def get_spot(account: dict, symbol: str = "NIFTY") -> Optional[float]:
    """
    Fetch current spot price for Nifty.
    Paper mode and live mode both use real data.
    """
    if account["paper_mode"]:
        return await _get_spot_paper(account, symbol)
    return await _get_spot_live(account, symbol)


# Breeze uses different stock codes for indices
BREEZE_SYMBOL_MAP = {
    "BANKNIFTY": "CNXBAN",
    "NIFTY": "NIFTY",
}

async def _get_spot_live(account: dict, symbol: str) -> Optional[float]:
    """Fetch spot price via Breeze API."""
    breeze = get_breeze(account)
    if not breeze:
        return None
    breeze_symbol = BREEZE_SYMBOL_MAP.get(symbol, symbol)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: breeze.get_quotes(
            stock_code=breeze_symbol,
            exchange_code="NSE",
            expiry_date="",
            product_type="cash",
            right="",
            strike_price=""
        ))
        nse_rows = [r for r in result["Success"] if r.get("exchange_code") in ("NSE", "NFO")]
        ltp = float(nse_rows[0]["ltp"]) if nse_rows else 0.0
        logger.debug(f"[{account['name']}] Spot {symbol}: ₹{ltp}")
        return ltp
    except Exception as e:
        logger.error(f"[{account['name']}] get_spot failed: {e}")
        return None


async def _get_spot_paper(account: dict, symbol: str) -> Optional[float]:
    """
    Paper mode: try live API first, fall back to mock price for offline testing.
    """
    live = await _get_spot_live(account, symbol)
    if live:
        return live
    # Retry once after 1 second
    await asyncio.sleep(1)
    live = await _get_spot_live(account, symbol)
    if live:
        return live
    logger.error(f"[{account['name']}] get_spot failed after retry — aborting, no mock price")
    return None


async def get_ltp(account: dict, symbol: str, strike: int,
                  option_type: str, expiry_str: str) -> Optional[float]:
    """Fetch last traded price. Retries once on empty/failed response."""
    breeze = get_breeze(account)
    if not breeze:
        mock = 150.0
        logger.info(f"[{account['name']}] Mock LTP Rs.{mock} for {symbol} {strike} {option_type}")
        return mock
    breeze_symbol = BREEZE_SYMBOL_MAP.get(symbol, symbol)
    for attempt in range(1, 4):
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: breeze.get_quotes(
                stock_code=breeze_symbol,
                exchange_code="NFO",
                expiry_date=expiry_str,
                product_type="options",
                right="call" if option_type == "CE" else "put",
                strike_price=str(strike)
            ))
            rows = [r for r in result["Success"] if r.get("exchange_code") in ("NSE", "NFO")]
            ltp = float(rows[0]["ltp"]) if rows else 0.0
            if ltp > 0:
                logger.debug(f"[{account['name']}] LTP {symbol} {strike} {option_type}: Rs.{ltp}")
                return ltp
            logger.warning(f"[{account['name']}] LTP=0 for {strike}{option_type} attempt {attempt}")
        except Exception as e:
            logger.error(f"[{account['name']}] get_ltp attempt {attempt} failed: {e}")
        if attempt < 3:
            await asyncio.sleep(2)
    logger.error(f"[{account['name']}] get_ltp failed after 3 attempts for {strike}{option_type}")
    return None


async def place_limit_order(
    account: dict,
    action: str,
    stock_code: str,          # "BUY" or "SELL"
    strike: int,
    option_type: str,     # "CE" or "PE"
    expiry_str: str,
    quantity: int,
    limit_price: float,
    timeout_seconds: int = 10,
) -> Tuple[Optional[str], Optional[float]]:
    """
    Place an aggressive limit order and wait for fill.
    Returns (order_id, fill_price) or (None, None) on failure.
    """
    breeze = get_breeze(account)
    if not breeze:
        logger.error(f"[{account['name']}] No Breeze connection for live order")
        return None, None

    try:
        loop = asyncio.get_event_loop()
        breeze_stock = BREEZE_SYMBOL_MAP.get(stock_code, stock_code)
        result = await loop.run_in_executor(None, lambda: breeze.place_order(
            stock_code=breeze_stock,
            exchange_code="NFO",
            product="options",
            action=action.lower(),
            order_type="limit",
            stoploss="0",
            quantity=str(quantity),
            price=str(limit_price),
            validity="day",
            validity_date=datetime.today().strftime("%Y-%m-%dT07:00:00.000Z"),
            disclosed_quantity="0",
            expiry_date=expiry_str,
            right="call" if option_type == "CE" else "put",
            strike_price=str(strike),
            user_remark="SMBALGOUTLRG",
            order_type_fresh="limit",
            order_rate_fresh=str(limit_price),
        ))

        order_id = result.get("Success", {}).get("order_id")
        if not order_id:
            logger.error(f"[{account['name']}] Order placement failed: {result}")
            return None, None

        logger.info(f"[{account['name']}] Order placed: {order_id}")

        # Poll for fill
        fill_price = await wait_for_fill(account, order_id, timeout_seconds)
        return order_id, fill_price

    except Exception as e:
        logger.error(f"[{account['name']}] place_limit_order failed: {e}")
        return None, None


async def wait_for_fill(account: dict, order_id: str,
                         timeout_seconds: int) -> Optional[float]:
    """Poll order status until filled or timeout."""
    breeze = get_breeze(account)
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    loop = asyncio.get_event_loop()

    while asyncio.get_event_loop().time() < deadline:
        try:
            result = await loop.run_in_executor(None, lambda: breeze.get_order_detail(
                exchange_code="NFO",
                order_id=order_id
            ))
            status = result.get("Success", [{}])[0].get("status", "")
            if status.lower() == "executed":
                fill_price = float(result["Success"][0]["average_price"])
                return fill_price
            elif status.lower() in ("cancelled", "rejected"):
                logger.warning(f"[{account['name']}] Order {order_id} {status}")
                return None
        except Exception as e:
            logger.error(f"[{account['name']}] Order status check failed: {e}")

        await asyncio.sleep(2)

    # Timeout — cancel the order
    logger.warning(f"[{account['name']}] Order {order_id} timed out. Cancelling.")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: breeze.cancel_order(
            exchange_code="NFO", order_id=order_id
        ))
    except Exception as e:
        logger.error(f"[{account['name']}] Cancel order failed: {e}")

    return None
