"""
SMB Algo — Account Manager
Loads account configs from environment variables.
Supports up to 4 accounts. Each account is independently configurable.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

MAX_ACCOUNTS = 4


def _load_account(n: int) -> Optional[dict]:
    """Load account N config from environment. Returns None if not configured."""
    prefix = f"ACCOUNT{n}_"
    env = __import__("dotenv").dotenv_values("/opt/smb-algo/.env")
    api_key = env.get(f"{prefix}API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "name":             env.get(f"{prefix}NAME", f"Account-{n}"),
        "api_key":          api_key,
        "api_secret":       env.get(f"{prefix}API_SECRET", ""),
        "session_token":    env.get(f"{prefix}SESSION_TOKEN", ""),
        "quantity_lots":    int(env.get(f"{prefix}QUANTITY_LOTS", "1")),
        "daily_loss_limit": float(env.get(f"{prefix}DAILY_LOSS_LIMIT", "5000")),
        "limit_buffer":     float(env.get(f"{prefix}LIMIT_BUFFER", "5")),
        "preclosure_lots":  int(env.get(f"{prefix}PRECLOSURE_LOTS", "0")),
        "profit_trigger":   float(env.get(f"{prefix}PROFIT_TRIGGER", "40")),
        "loss_trigger":     float(env.get(f"{prefix}LOSS_TRIGGER", "40")),
        "paper_mode":       env.get(f"{prefix}PAPER_MODE", "true").lower() == "true",
        "active":           env.get(f"{prefix}ACTIVE", "true").lower() == "true",
    }


def get_all_accounts() -> list[dict]:
    """Returns all configured accounts (active or not)."""
    accounts = []
    for n in range(1, MAX_ACCOUNTS + 1):
        account = _load_account(n)
        if account:
            accounts.append(account)
    return accounts


def get_active_accounts() -> list[dict]:
    """Returns only active accounts — these receive signals and place orders."""
    return [a for a in get_all_accounts() if a["active"]]


def get_account(name: str) -> Optional[dict]:
    """Returns a specific account by name."""
    for account in get_all_accounts():
        if account["name"] == name:
            return account
    return None


def update_session_token(name: str, token: str):
    """
    Update session token for an account in memory.
    Called after morning login via frontend.
    Note: Does not persist to .env — tokens are ephemeral (daily).
    """
    # In a running app, session tokens are stored in a runtime dict
    # Updated via the /auth/breeze/callback endpoint each morning
    _session_tokens[name] = token
    logger.info(f"Session token updated for account: {name}")


# Runtime token store (in-memory, reset on restart)
_session_tokens: dict = {}


def get_session_token(name: str) -> Optional[str]:
    """Get the current runtime session token for an account."""
    # First check runtime store (set via morning login)
    if name in _session_tokens:
        return _session_tokens[name]
    # Fall back to env (useful for development)
    account = get_account(name)
    return account.get("session_token") if account else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    accounts = get_all_accounts()
    if accounts:
        print(f"✓ Loaded {len(accounts)} account(s):")
        for a in accounts:
            print(f"  - {a['name']} | Paper: {a['paper_mode']} | "
                  f"Active: {a['active']} | Lots: {a['quantity_lots']} | "
                  f"Loss limit: ₹{a['daily_loss_limit']}")
    else:
        print("No accounts configured yet. Add ACCOUNT1_* to .env")


def clear_connection(account_name: str):
    """Proxy to breeze_client — clears cached connection on token refresh."""
    from core.breeze_client import clear_connection as _clear
    _clear(account_name)
