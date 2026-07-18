"""
SMB Algo — Strike Selection Engine
Selects the correct ITM option strike for a given spot price and signal direction.

Rules (Nifty, 50-point strike intervals):
  BUY signal  → ITM Call → strike immediately BELOW spot
               Formula: floor(spot / 50) * 50
               Example: spot=23740 → 23700 Call

  SELL signal → ITM Put  → strike immediately ABOVE spot
               Formula: ceil(spot / 50) * 50
               Example: spot=23740 → 23750 Put

Edge case: spot exactly on a strike (e.g. 23750)
  BUY  → 23750 - 50 = 23700 Call  (one step below)
  SELL → 23750 + 50 = 23800 Put   (one step above)
"""

import math
import logging
from enum import Enum

logger = logging.getLogger(__name__)

STRIKE_INTERVAL = 50  # Nifty options: 50-point intervals


class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CE"
    PUT  = "PE"


def get_itm_strike(spot: float, signal: Signal, interval: int = STRIKE_INTERVAL) -> int:
    """
    Returns the slightly ITM strike price for a given spot and signal.

    Args:
        spot:     Current spot price of Nifty
        signal:   Signal.BUY → Call, Signal.SELL → Put
        interval: Strike interval (default 50 for Nifty)

    Returns:
        Strike price as integer
    """
    if signal == Signal.BUY:
        # ITM Call: strike immediately below spot
        strike = math.floor(spot / interval) * interval
        # If spot is exactly on a strike, go one step lower
        if strike == spot:
            strike = int(spot) - interval
        logger.debug(f"BUY signal | Spot: {spot} → ITM Call strike: {strike}")
        return int(strike)

    elif signal == Signal.SELL:
        # ITM Put: strike immediately above spot
        strike = math.ceil(spot / interval) * interval
        # If spot is exactly on a strike, go one step higher
        if strike == spot:
            strike = int(spot) + interval
        logger.debug(f"SELL signal | Spot: {spot} → ITM Put strike: {strike}")
        return int(strike)

    raise ValueError(f"Invalid signal: {signal}")


def get_option_type(signal: Signal) -> OptionType:
    """Returns the option type (CE/PE) for a given signal."""
    return OptionType.CALL if signal == Signal.BUY else OptionType.PUT


def build_option_symbol(strike: int, option_type: OptionType, expiry_str: str,
                         instrument: str = "NIFTY") -> str:
    """
    Builds the option symbol string for Breeze API.
    Format: NIFTY (instrument field separate in Breeze — this is for logging/display)
    Breeze uses separate fields: stock_code, expiry_date, strike_price, right (call/put)
    This function returns a human-readable label.

    Example: "NIFTY 23700 CE 10-JUN-2026"
    """
    return f"{instrument} {strike} {option_type.value} {expiry_str}"


if __name__ == "__main__":
    # ── Self-test ────────────────────────────────────────────────────────────
    logging.basicConfig(level=logging.DEBUG)

    test_cases = [
        # (spot,    signal,       expected_strike, expected_type)
        (23740.0,  Signal.BUY,   23700,           OptionType.CALL),
        (23740.0,  Signal.SELL,  23750,           OptionType.PUT),
        (23750.0,  Signal.BUY,   23700,           OptionType.CALL),  # exactly on strike
        (23750.0,  Signal.SELL,  23800,           OptionType.PUT),   # exactly on strike
        (23701.0,  Signal.BUY,   23700,           OptionType.CALL),  # just above strike
        (23699.0,  Signal.SELL,  23700,           OptionType.PUT),   # just below strike
        (24000.0,  Signal.BUY,   24000 - 50,      OptionType.CALL),  # round number
        (24000.0,  Signal.SELL,  24000 + 50,      OptionType.PUT),   # round number
    ]

    print("\n" + "="*60)
    print("STRIKE SELECTION ENGINE TEST RESULTS")
    print("="*60)
    all_passed = True
    for spot, signal, expected_strike, expected_type in test_cases:
        strike = get_itm_strike(spot, signal)
        opt_type = get_option_type(signal)
        passed = strike == expected_strike and opt_type == expected_type
        all_passed = all_passed and passed
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"\n{status} | Spot: {spot:8.1f} | Signal: {signal.value:4s} "
              f"| Strike: {strike:6d} {opt_type.value} "
              f"| Expected: {expected_strike:6d} {expected_type.value}")

    print("\n" + "="*60)
    print(f"Result: {'ALL TESTS PASSED ✓' if all_passed else 'SOME TESTS FAILED ✗'}")
    print("="*60)
