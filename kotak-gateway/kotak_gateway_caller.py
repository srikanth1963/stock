"""
kotak_gateway_caller.py

REFERENCE MODULE — not meant to run standalone. This shows the retry/
idempotency logic that needs to be added to Primary's order_router.py
wherever it currently calls breeze_client for a Kotak-routed account.

Integration point: in order_router.py, wherever an order action is
decided (entry/exit/partial_exit), branch on the account's configured
broker. For broker == "breeze", call breeze_client as today. For
broker == "kotak", call execute_via_kotak_gateway() below instead.
"""

import time
import uuid
import logging
import requests

logger = logging.getLogger("kotak_gateway_caller")

KOTAK_GATEWAY_URL = "http://8.231.114.4:8010/execute"  # Kotak VM's static IP
REQUEST_TIMEOUT_SECONDS = 2
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1


def make_signal_id(account_id: str, symbol: str, action: str, timestamp: str) -> str:
    """Deterministic per-decision ID so retries never double-place an order.
    Called ONCE per actual decision, then reused across all retry attempts
    for that same decision."""
    return f"{account_id}-{symbol}-{action}-{timestamp}"


def execute_via_kotak_gateway(
    account_id: str,
    symbol: str,
    side: str,
    qty_lots: int,
    action: str,
    signal_id: str,
    lot_size: int,
    exit_order_id: str = None,
    reason: str = "",
) -> dict:
    """
    Calls the Kotak execution gateway with retries. Returns the gateway's
    response dict on success. Raises RuntimeError after all retries are
    exhausted — caller (order_router.py) should catch this and fire the
    same critical alert used for other failed-order scenarios today.
    """
    payload = {
        "action": action,
        "symbol": symbol,
        "side": side,
        "qty_lots": qty_lots,
        "order_type": "MARKET",
        "signal_id": signal_id,
        "reason": reason,
        "lot_size": lot_size,
    }
    if exit_order_id:
        payload["exit_order_id"] = exit_order_id

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(KOTAK_GATEWAY_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                logger.info("Kotak gateway success on attempt %d: %s", attempt, resp.json())
                return resp.json()
            # 4xx (e.g. 409 exit-guard rejection) — don't retry, it's not a
            # transient failure, it's a definitive rejection.
            if 400 <= resp.status_code < 500:
                logger.error("Kotak gateway rejected (attempt %d): %s", attempt, resp.text)
                raise RuntimeError(f"Kotak gateway rejected request: {resp.text}")
            # 5xx — treat as transient, retry.
            last_error = f"HTTP {resp.status_code}: {resp.text}"
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)

        logger.warning("Kotak gateway attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, last_error)
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)

    # All retries exhausted — this must surface as loudly as a failed
    # Breeze order does today.
    raise RuntimeError(f"Kotak gateway failed after {MAX_ATTEMPTS} attempts: {last_error}")


# ---------------------------------------------------------------------------
# EXAMPLE integration shape inside order_router.py (illustrative, not exact
# to your existing code — you'll need to fit this into the actual function
# that currently branches on action type):
#
#   if account.broker == "kotak":
#       signal_id = make_signal_id(account.id, symbol, action, str(datetime.now()))
#       try:
#           result = execute_via_kotak_gateway(
#               account_id=account.id, symbol=symbol, side=side,
#               qty_lots=quantity_lots, action=action, signal_id=signal_id,
#               lot_size=lot_size, exit_order_id=existing_trade.kotak_order_id,
#               reason=reason,
#           )
#           # write result["order_id"], result["fill_price"] into trade record
#       except RuntimeError as e:
#           send_critical_alert(f"Kotak order failed for {account.id}: {e}")
#   else:
#       # existing breeze_client path, unchanged
#       ...
# ---------------------------------------------------------------------------
