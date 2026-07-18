"""
Strike Selection Engine — SMB Algo Stocks
Standalone module. Given a stock and direction, selects the option strike
to trade based on futures price + OI within an ATM window.

Locked design:
1. Fetch futures LTP for current expiry -> ATM reference (not spot)
2. Fetch option chain -> derive strike interval from consecutive strikes
3. ATM = round(futures price to nearest strike interval)
4. Filter +/-4 strikes around ATM (9 strikes total)
5. Select strike with highest OI within that window

Usage:
    from strike_selector import select_strike

    result = select_strike(
        breeze=breeze_session,
        breeze_code='INFTEC',
        expiry_date='2026-07-28T06:00:00.000Z',
        direction='BUY',      # BUY -> Call, SELL -> Put
        window=4
    )

Returns a dict with the selected strike, OI, price quotes, and diagnostics
for every candidate strike considered (useful for logging/debugging).
"""

from datetime import datetime


class StrikeSelectionError(Exception):
    """Raised when strike selection cannot complete (missing data, API error, etc)."""
    pass


def get_futures_price(breeze, breeze_code, expiry_date):
    """
    Fetch the current futures price for a stock+expiry.
    Returns float futures price.
    """
    resp = breeze.get_quotes(
        stock_code=breeze_code,
        exchange_code="NFO",
        product_type="futures",
        expiry_date=expiry_date,
        right="others",
        strike_price="0"
    )

    if resp.get("Status") != 200:
        raise StrikeSelectionError(f"get_quotes failed: {resp.get('Error')}")

    rows = resp.get("Success") or []
    if not rows:
        raise StrikeSelectionError(f"No futures quote returned for {breeze_code}")

    futures_price = float(rows[0].get("ltp", 0))
    if futures_price <= 0:
        raise StrikeSelectionError(f"Invalid futures price for {breeze_code}: {futures_price}")

    return futures_price


def get_option_chain(breeze, breeze_code, expiry_date, right):
    """
    Fetch the full option chain (one side: call or put) for a stock+expiry.
    right: 'call' or 'put'
    Returns list of dicts, one per strike.
    """
    resp = breeze.get_option_chain_quotes(
        stock_code=breeze_code,
        exchange_code="NFO",
        product_type="options",
        expiry_date=expiry_date,
        right=right,
        strike_price="0"
    )

    if resp.get("Status") != 200:
        raise StrikeSelectionError(f"get_option_chain_quotes failed: {resp.get('Error')}")

    rows = resp.get("Success") or []
    if not rows:
        raise StrikeSelectionError(f"Empty option chain for {breeze_code} {right}")

    return rows


def derive_strike_interval(chain_rows):
    """
    Derive the strike interval from consecutive strikes in the chain.
    Uses the most common gap between sorted unique strikes (robust to
    occasional missing/illiquid strikes in the raw data).
    """
    strikes = sorted({float(r["strike_price"]) for r in chain_rows if float(r.get("strike_price", 0)) > 0})

    if len(strikes) < 2:
        raise StrikeSelectionError("Not enough strikes to derive interval")

    gaps = [round(strikes[i+1] - strikes[i], 2) for i in range(len(strikes) - 1)]

    # Most common gap = interval (handles occasional missing strikes gracefully)
    gap_counts = {}
    for g in gaps:
        gap_counts[g] = gap_counts.get(g, 0) + 1
    interval = max(gap_counts, key=gap_counts.get)

    return interval


def round_to_interval(price, interval):
    """Round a price to the nearest strike interval."""
    return round(price / interval) * interval


def select_strike(breeze, breeze_code, expiry_date, direction, window=4):
    """
    Main entry point. Selects the strike to trade.

    Args:
        breeze: authenticated BreezeConnect session
        breeze_code: Breeze stock code (e.g. 'INFTEC')
        expiry_date: ISO format expiry string e.g. '2026-07-28T06:00:00.000Z'
        direction: 'BUY' or 'SELL' -> determines call vs put
        window: number of strikes above/below ATM to consider (default 4)

    Returns:
        dict {
            'breeze_code': str,
            'right': 'call' or 'put',
            'futures_price': float,
            'strike_interval': float,
            'atm_strike': float,
            'selected_strike': float,
            'selected_oi': float,
            'selected_ltp': float,
            'selected_bid': float,
            'selected_ask': float,
            'candidates': [list of all strikes considered with their OI, for logging]
        }

    Raises:
        StrikeSelectionError on any failure (missing data, API error, no valid strikes).
    """
    if direction not in ('BUY', 'SELL'):
        raise StrikeSelectionError(f"Invalid direction: {direction}")

    right = 'call' if direction == 'BUY' else 'put'

    # Step 1: Futures price (ATM reference)
    futures_price = get_futures_price(breeze, breeze_code, expiry_date)

    # Step 2: Option chain for the relevant side
    chain_rows = get_option_chain(breeze, breeze_code, expiry_date, right)

    # Step 3: Derive strike interval, compute ATM
    interval = derive_strike_interval(chain_rows)
    atm_strike = round_to_interval(futures_price, interval)

    # Step 4: Filter +/- window strikes around ATM
    window_strikes = [
        atm_strike + (i * interval)
        for i in range(-window, window + 1)
    ]

    candidates = []
    for row in chain_rows:
        strike = float(row.get("strike_price", 0))
        if strike not in window_strikes:
            continue

        oi = float(row.get("open_interest", 0) or 0)
        ltp = float(row.get("ltp", 0) or 0)
        bid = float(row.get("best_bid_price", 0) or 0)
        ask = float(row.get("best_offer_price", 0) or 0)

        candidates.append({
            "strike": strike,
            "oi": oi,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
        })

    if not candidates:
        raise StrikeSelectionError(
            f"No candidate strikes found in window for {breeze_code} "
            f"(ATM={atm_strike}, interval={interval})"
        )

    # Step 5: Highest OI wins
    selected = max(candidates, key=lambda c: c["oi"])

    if selected["oi"] <= 0:
        raise StrikeSelectionError(
            f"Selected strike {selected['strike']} for {breeze_code} has zero OI — "
            f"likely illiquid, skipping trade"
        )

    return {
        "breeze_code": breeze_code,
        "right": right,
        "futures_price": futures_price,
        "strike_interval": interval,
        "atm_strike": atm_strike,
        "selected_strike": selected["strike"],
        "selected_oi": selected["oi"],
        "selected_ltp": selected["ltp"],
        "selected_bid": selected["bid"],
        "selected_ask": selected["ask"],
        "candidates": sorted(candidates, key=lambda c: c["strike"]),
    }


# ── Standalone test runner ───────────────────────────────────────────────────
if __name__ == '__main__':
    import os
    import json
    from dotenv import load_dotenv
    from breeze_connect import BreezeConnect

    load_dotenv("/opt/smb-algo/.env")

    API_KEY    = os.getenv("ACCOUNT1_API_KEY")
    API_SECRET = os.getenv("ACCOUNT1_API_SECRET")
    SESSION    = os.getenv("ACCOUNT1_SESSION_TOKEN")

    breeze = BreezeConnect(api_key=API_KEY)
    breeze.generate_session(api_secret=API_SECRET, session_token=SESSION)

    # Test parameters — adjust as needed
    TEST_STOCK_CODE = "INFTEC"
    TEST_EXPIRY     = "2026-07-28T06:00:00.000Z"
    TEST_DIRECTION  = "BUY"

    print(f"Testing strike selection for {TEST_STOCK_CODE} ({TEST_DIRECTION})...")
    try:
        result = select_strike(
            breeze=breeze,
            breeze_code=TEST_STOCK_CODE,
            expiry_date=TEST_EXPIRY,
            direction=TEST_DIRECTION,
            window=4
        )
        print(json.dumps(result, indent=2, default=str))
    except StrikeSelectionError as e:
        print(f"Strike selection failed: {e}")
