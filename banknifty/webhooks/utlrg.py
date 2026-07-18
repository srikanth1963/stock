"""
SMB Algo — UT-LRG Webhook Receiver
Receives TradingView alerts and processes signals.

TradingView sends POST to /webhook/utlrg with JSON:
  {"signal": "BUY", "symbol": "NIFTY"}
  {"signal": "SELL", "symbol": "NIFTY"}

Processing:
  1. Validate payload
  2. Log raw webhook
  3. Check deduplication (ignore same-direction in same candle window)
  4. Store signal state
  5. Schedule order execution at next candle open
"""

import logging
from datetime import datetime, timezone, time
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator

from core.database import get_db, WebhookLog
from core.signal_state import save_signal, is_new_signal
from core.order_router import handle_signal, exit_only_if_reversed

logger = logging.getLogger(__name__)

router = APIRouter()

STRATEGY_ID = "utlrg"

# Trading window
TRADING_START = time(9, 26)   # 9:20 AM IST — matches morning scheduler
TRADING_END   = time(15, 0)   # 3:00 PM IST — last entry


class SignalPayload(BaseModel):
    signal: str
    symbol: str = "NIFTY"
    spot_price: float = None

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v):
        v = v.upper().strip()
        if v not in ("BUY", "SELL"):
            raise ValueError(f"Signal must be BUY or SELL, got: {v}")
        return v

def parse_payload(raw: str) -> SignalPayload:
    raw = raw.strip()
    if raw.startswith("{"):
        import json
        data = json.loads(raw)
        return SignalPayload(**data)
    parts = raw.split()
    signal = parts[0].upper().strip() if len(parts) > 0 else "BUY"
    symbol = parts[1].upper().strip() if len(parts) > 1 else "NIFTY"
    spot = float(parts[2]) if len(parts) > 2 else None
    return SignalPayload(signal=signal, symbol=symbol, spot_price=spot)


def is_within_trading_window() -> bool:
    """Check if current IST time is within the trading window."""
    from zoneinfo import ZoneInfo
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).time()
    return TRADING_START <= now_ist <= TRADING_END


def log_webhook(strategy_id: str, raw: str, signal: str = None,
                processed: bool = False, error: str = None):
    """Log raw webhook to database for audit trail."""
    with get_db() as db:
        db.add(WebhookLog(
            strategy_id=strategy_id,
            raw_payload=raw,
            signal=signal,
            processed=processed,
            error=error,
            received_at=datetime.now(timezone.utc)
        ))


@router.post("/webhook/utlrg")
async def receive_signal(
    request: Request,
    background_tasks: BackgroundTasks
):
    # ── Secret validation ─────────────────────────────────────────────────────
    import os
    expected = os.getenv("WEBHOOK_SECRET", "")
    if expected:
        received = request.query_params.get("secret", "")
        if received != expected:
            logger.warning(f"[{STRATEGY_ID}] Invalid webhook secret — rejected")
            raise HTTPException(status_code=403, detail="Invalid secret")
    """
    Endpoint for TradingView UT-LRG alerts.
    Validates, logs, deduplicates, stores signal, triggers order routing.
    """
    raw_body = await request.body()
    raw_str = raw_body.decode("utf-8")
    logger.info(f"[{STRATEGY_ID}] Webhook received: {raw_str}")

    # ── Parse payload ────────────────────────────────────────────────────────
    try:
        payload = parse_payload(raw_str)
    except Exception as e:
        log_webhook(STRATEGY_ID, raw_str, error=str(e))
        logger.error(f"[{STRATEGY_ID}] Invalid payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    signal = payload.signal
    spot_price = payload.spot_price
    logger.info(f"[{STRATEGY_ID}] Parsed: signal={signal} spot=Rs.{spot_price}")

    # ── Check trading window ─────────────────────────────────────────────────
    if not is_within_trading_window():
        from zoneinfo import ZoneInfo
        from datetime import date
        from core.order_router import get_open_trade
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")

        # Check if open trade is in the same direction as incoming signal
        open_trade = get_open_trade("Primary", STRATEGY_ID, date.today())
        if open_trade and open_trade["signal"] == signal:
            msg = f"Signal received at {now_ist} IST — same direction as open trade. No action."
            logger.info(f"[{STRATEGY_ID}] {msg}")
            log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=False, error=msg)
            return {"status": "ignored", "signal": signal, "message": msg}

        # Different direction — save signal and exit position if open
        msg = f"Signal received at {now_ist} IST — outside trading window. Stored only."
        logger.info(f"[{STRATEGY_ID}] {msg}")
        save_signal(STRATEGY_ID, signal)
        log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=False, error=msg)
        background_tasks.add_task(exit_only_if_reversed, STRATEGY_ID, signal)
        return {"status": "stored", "signal": signal, "message": msg}

    # ── Deduplication ────────────────────────────────────────────────────────
    if not is_new_signal(STRATEGY_ID, signal):
        msg = f"Duplicate signal ignored: {signal} (same direction as current state)"
        logger.info(f"[{STRATEGY_ID}] {msg}")
        log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=False, error=msg)
        return {"status": "duplicate", "signal": signal, "message": msg}

    # ── Store signal ─────────────────────────────────────────────────────────
    save_signal(STRATEGY_ID, signal, candle_close=datetime.now(timezone.utc))
    log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=True)

    # ── Route to order handler (background — non-blocking) ───────────────────
    background_tasks.add_task(handle_signal, STRATEGY_ID, signal, spot_price)

    logger.info(f"[{STRATEGY_ID}] Signal accepted: {signal} → order routing started")
    return {"status": "accepted", "signal": signal}


@router.get("/webhook/utlrg/status")
async def webhook_status():
    """Health check — returns last known signal state."""
    from core.signal_state import get_last_signal
    state = get_last_signal(STRATEGY_ID)
    return {
        "strategy": STRATEGY_ID,
        "last_signal": state,
        "trading_window_active": is_within_trading_window()
    }
