"""
breeze_client.py — Shared Breeze session for SMB Algo Stocks
Single session shared across all operations on this VM/account.
"""
import os
import logging
from dotenv import load_dotenv
from breeze_connect import BreezeConnect

load_dotenv("/opt/smb-algo/.env")

logger = logging.getLogger(__name__)

# ── Breeze symbol map for special cases ──────────────────────────────────────
# NSE ticker -> Breeze code overrides (where they differ)
# Populated from stock_master at runtime, this is just a fallback
BREEZE_SYMBOL_MAP = {
    "BANKNIFTY": "CNXBAN",
    "FINNIFTY":  "NIFFIN",
    "MIDCPNIFTY":"NIFSEL",
    "NIFTYNXT50":"NIFNEX",
}

_breeze_instance = None


def get_breeze() -> BreezeConnect:
    """Return the singleton Breeze session, initialising if needed."""
    global _breeze_instance
    if _breeze_instance is None:
        _breeze_instance = _init_breeze()
    return _breeze_instance


def _init_breeze() -> BreezeConnect:
    from dotenv import dotenv_values
    env = dotenv_values("/opt/smb-algo/.env")
    api_key     = env.get("ACCOUNT1_API_KEY")
    api_secret  = env.get("ACCOUNT1_API_SECRET")
    session_token = env.get("ACCOUNT1_SESSION_TOKEN")

    if not all([api_key, api_secret, session_token]):
        raise RuntimeError("Missing Breeze credentials in .env")

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    logger.info("Breeze session initialised for stocks app")
    return breeze


def refresh_session() -> bool:
    """Re-initialise the Breeze session (called by Refresh Session button)."""
    global _breeze_instance
    try:
        _breeze_instance = _init_breeze()
        logger.info("Breeze session refreshed successfully")
        return True
    except Exception as e:
        logger.error(f"Breeze session refresh failed: {e}")
        return False


def get_ltp(breeze: BreezeConnect, breeze_code: str, expiry_date: str,
            product_type: str = "options", right: str = "call",
            strike_price: str = "0") -> float | None:
    """Fetch LTP for a given instrument. Returns None on failure."""
    try:
        resp = breeze.get_quotes(
            stock_code=breeze_code,
            exchange_code="NFO",
            product_type=product_type,
            expiry_date=expiry_date,
            right=right,
            strike_price=strike_price
        )
        if resp.get("Status") == 200:
            rows = resp.get("Success") or []
            if rows:
                return float(rows[0].get("ltp", 0))
    except Exception as e:
        logger.error(f"get_ltp failed for {breeze_code}: {e}")
    return None
