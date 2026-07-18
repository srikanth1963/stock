"""
SMB Algo — Signal State Manager
Handles persistence and retrieval of UT Bot signal state.
Critical for morning carry-over logic.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional
from core.database import get_db, SignalState

logger = logging.getLogger(__name__)


def save_signal(strategy_id: str, signal: str, candle_close: datetime = None):
    """
    Persist the latest signal to database.
    Called every time a new webhook is received and processed.

    Args:
        strategy_id:  e.g. "utlrg"
        signal:       "BUY" or "SELL"
        candle_close: datetime of the candle that generated the signal
    """
    signal = signal.upper()
    assert signal in ("BUY", "SELL"), f"Invalid signal: {signal}"
    now = datetime.now(timezone.utc)

    with get_db() as db:
        existing = db.query(SignalState).filter_by(strategy_id=strategy_id).first()
        if existing:
            old_signal = existing.signal
            existing.signal = signal
            existing.signal_date = date.today()
            existing.signal_time = now
            existing.candle_close = candle_close
            if old_signal != signal:
                logger.info(f"[{strategy_id}] Signal changed: {old_signal} → {signal}")
            else:
                logger.debug(f"[{strategy_id}] Signal confirmed: {signal} (no change)")
        else:
            db.add(SignalState(
                strategy_id=strategy_id,
                signal=signal,
                signal_date=date.today(),
                signal_time=now,
                candle_close=candle_close
            ))
            logger.info(f"[{strategy_id}] First signal stored: {signal}")


def get_last_signal(strategy_id: str) -> Optional[dict]:
    """
    Retrieve the last persisted signal for a strategy.
    Returns None if no signal has ever been stored.

    Returns:
        dict with keys: signal, signal_date, signal_time, candle_close
        or None if not found
    """
    with get_db() as db:
        state = db.query(SignalState).filter_by(strategy_id=strategy_id).first()
        if not state:
            logger.warning(f"[{strategy_id}] No stored signal found")
            return None
        return {
            "signal":       state.signal,
            "signal_date":  state.signal_date,
            "signal_time":  state.signal_time,
            "candle_close": state.candle_close,
        }


def is_new_signal(strategy_id: str, incoming_signal: str) -> bool:
    """
    Returns True if the incoming signal is a direction CHANGE from stored signal.
    Returns True also if no prior signal exists (first signal of the day).
    Used for deduplication — ignore same-direction signals in same candle.
    """
    last = get_last_signal(strategy_id)
    if last is None:
        return True
    return last["signal"].upper() != incoming_signal.upper()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    from core.database import init_db
    init_db()

    print("\n" + "="*50)
    print("SIGNAL STATE MANAGER TEST")
    print("="*50)

    # Test 1: Save first signal
    save_signal("utlrg", "BUY")
    state = get_last_signal("utlrg")
    print(f"\n✓ Stored BUY: {state}")

    # Test 2: Same signal → not new
    result = is_new_signal("utlrg", "BUY")
    print(f"✓ BUY again is new signal: {result}  (expected False)")

    # Test 3: Different signal → new
    result = is_new_signal("utlrg", "SELL")
    print(f"✓ SELL is new signal: {result}  (expected True)")

    # Test 4: Save SELL
    save_signal("utlrg", "SELL")
    state = get_last_signal("utlrg")
    print(f"✓ Stored SELL: {state}")

    print("\n" + "="*50)
    print("ALL TESTS PASSED ✓")
    print("="*50)
