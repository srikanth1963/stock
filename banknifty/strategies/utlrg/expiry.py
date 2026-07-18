"""
SMB Algo — Expiry Date Engine
Determines the correct Nifty weekly options expiry date for any given trading day.
Nifty weekly expiry: Tuesday
Rules:
  1. Wed–Fri: use this week's Tuesday
  2. Mon or Tue: skip to next week's Tuesday
  3. If Tuesday is NSE holiday: shift to Monday, then Friday
  4. If computed expiry == today: shift to next week
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

HOLIDAYS_FILE = Path(__file__).parent.parent.parent / "config" / "nse_holidays.json"


@lru_cache(maxsize=1)
def load_nse_holidays() -> frozenset:
    """
    Load NSE holidays from config file. Cached after first load.
    Cache is cleared at midnight by the scheduler (see main.py).
    """
    try:
        data = json.loads(HOLIDAYS_FILE.read_text())

        # ── Staleness check ──────────────────────────────────────────────────
        valid_through = data.get("valid_through", "")
        if valid_through:
            valid_date = date.fromisoformat(valid_through)
            today = date.today()
            days_remaining = (valid_date - today).days

            if days_remaining < 0:
                logger.error(
                    f"NSE HOLIDAY CALENDAR EXPIRED on {valid_through}! "
                    f"Expiry calculations may be incorrect. "
                    f"Please update config/nse_holidays.json immediately."
                )
            elif days_remaining <= 30:
                logger.warning(
                    f"NSE holiday calendar expires in {days_remaining} days ({valid_through}). "
                    f"Download the next year's calendar from nseindia.com and update "
                    f"config/nse_holidays.json before year end."
                )

        # ── Parse holidays ───────────────────────────────────────────────────
        holidays_by_year = data.get("holidays", {})
        all_dates = set()

        for year, entries in holidays_by_year.items():
            for entry in entries:
                d_str = entry.get("date", "")
                # Skip placeholder entries
                if "placeholder" in entry.get("day", "").lower():
                    continue
                try:
                    all_dates.add(date.fromisoformat(d_str))
                except ValueError:
                    logger.warning(f"Invalid holiday date skipped: {d_str}")

        holidays = frozenset(all_dates)
        logger.info(
            f"Loaded {len(holidays)} NSE holidays | "
            f"Valid through: {valid_through} | "
            f"Source: {data.get('last_updated', 'unknown')}"
        )
        return holidays

    except Exception as e:
        logger.error(f"Failed to load NSE holidays: {e}")
        return frozenset()


def get_holiday_status() -> dict:
    """
    Returns holiday calendar health status for the dashboard.
    Called by the API to show calendar status on frontend.
    """
    try:
        data = json.loads(HOLIDAYS_FILE.read_text())
        valid_through = data.get("valid_through", "")
        last_updated = data.get("last_updated", "")
        holidays = load_nse_holidays()

        status = "ok"
        message = f"Calendar valid through {valid_through}"

        if valid_through:
            days_remaining = (date.fromisoformat(valid_through) - date.today()).days
            if days_remaining < 0:
                status = "expired"
                message = f"EXPIRED on {valid_through} — update immediately!"
            elif days_remaining <= 30:
                status = "warning"
                message = f"Expires in {days_remaining} days — update soon"

        return {
            "status": status,
            "message": message,
            "last_updated": last_updated,
            "valid_through": valid_through,
            "holiday_count": len(holidays),
            "update_instructions": "Download from nseindia.com > About NSE > Circulars > 'trading holidays <year>'"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def is_trading_day(d: date) -> bool:
    """Returns True if the given date is a trading day (not weekend, not holiday)."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in load_nse_holidays()


def get_expiry_date(today: date = None) -> date:
    """
    Returns the correct Nifty weekly expiry date for a given trading day.

    Args:
        today: The trading date to evaluate. Defaults to date.today().

    Returns:
        The correct expiry date as a date object.
    """
    if today is None:
        today = date.today()

    holidays = load_nse_holidays()

    # ── Step 1: Find this week's Tuesday ────────────────────────────────────
    # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    days_to_tuesday = (1 - today.weekday()) % 7
    if days_to_tuesday == 0:
        # Today IS Tuesday
        this_tuesday = today
    else:
        this_tuesday = today + timedelta(days=days_to_tuesday)

    # ── Step 2: Resolve holiday shift for this Tuesday ───────────────────────
    expiry = this_tuesday

    if expiry in holidays:
        # Tuesday is holiday → try Monday
        monday = expiry - timedelta(days=1)
        if monday not in holidays and monday.weekday() < 5:
            expiry = monday
            logger.info(f"Expiry shifted: {this_tuesday} (holiday) → {expiry} (Monday)")
        else:
            # Monday also holiday or weekend → try Friday
            friday = expiry - timedelta(days=4)
            expiry = friday
            logger.info(f"Expiry shifted: {this_tuesday} (holiday) → {expiry} (Friday)")

    # ── Step 3: Mon/Tue trading → skip to next week ──────────────────────────
    # Also handles: today IS the expiry day (shifted or normal)
    if today.weekday() in (0, 1) or expiry == today:
        # Move to next week's Tuesday
        next_tuesday = this_tuesday + timedelta(days=7)
        expiry = next_tuesday

        # Resolve holidays for next week's Tuesday too
        if expiry in holidays:
            monday = expiry - timedelta(days=1)
            if monday not in holidays and monday.weekday() < 5:
                expiry = monday
                logger.info(f"Next week expiry shifted: {next_tuesday} (holiday) → {expiry}")
            else:
                friday = expiry - timedelta(days=4)
                expiry = friday
                logger.info(f"Next week expiry shifted: {next_tuesday} (holiday) → {expiry}")

    logger.debug(f"Expiry for {today} ({today.strftime('%A')}): {expiry} ({expiry.strftime('%A')})")
    return expiry


def get_expiry_string(today: date = None) -> str:
    """
    Returns expiry date as formatted string for Breeze API.
    Breeze expects format: '26-JUN-2026'
    """
    expiry = get_expiry_date(today)
    return expiry.strftime("%d-%b-%Y")


if __name__ == "__main__":
    # ── Self-test ────────────────────────────────────────────────────────────
    logging.basicConfig(level=logging.DEBUG)
    test_cases = [
        # (date_str,           expected_weekday_of_expiry, description)
        ("2026-06-04", "Thursday",  "Normal Thursday → this Tuesday (Jun 9)... wait Jun 9 is Tue"),
        ("2026-06-03", "Wednesday", "Normal Wednesday → this Tuesday was Jun 2, next is Jun 9"),
        ("2026-06-08", "Monday",    "Monday → skip to next week Tuesday Jun 16"),
        ("2026-06-09", "Tuesday",   "Tuesday expiry day → skip to next week Jun 16"),
        ("2026-06-10", "Wednesday", "Wednesday after expiry → next Tuesday Jun 16"),
    ]

    print("\n" + "="*60)
    print("EXPIRY ENGINE TEST RESULTS")
    print("="*60)
    for date_str, _, description in test_cases:
        d = date.fromisoformat(date_str)
        expiry = get_expiry_date(d)
        expiry_str = get_expiry_string(d)
        print(f"\nDate    : {d} ({d.strftime('%A')})")
        print(f"Expiry  : {expiry} ({expiry.strftime('%A')}) → Breeze: {expiry_str}")
        print(f"Case    : {description}")
    print("\n" + "="*60)


# ── BankNifty Monthly Expiry (with 2-day rollover) ────────────────────────────

MONTHLY_EXPIRY_FILE = Path(__file__).parent.parent.parent / "config" / "monthly_expiry_2026.json"


@lru_cache(maxsize=1)
def load_monthly_expiries() -> list:
    """Load sorted list of monthly expiry dates from config."""
    data = json.load(open(MONTHLY_EXPIRY_FILE))
    return sorted(date.fromisoformat(d) for d in data["expiry_dates"])


def get_monthly_expiry_date(today: date = None) -> date:
    """
    Returns the monthly expiry date to trade for 'today'.
    Rollover rule: if today is the expiry day, or the trading day immediately
    before it, trade the NEXT month's expiry instead.
    """
    if today is None:
        today = date.today()
    expiries = load_monthly_expiries()
    current = next((e for e in expiries if e >= today), None)
    if current is None:
        raise ValueError(f"No monthly expiry found for {today} - update monthly_expiry_2026.json")
    prev_day = current - timedelta(days=1)
    rollover_window = {current}
    if is_trading_day(prev_day):
        rollover_window.add(prev_day)
    if today in rollover_window:
        next_expiry = next((e for e in expiries if e > current), None)
        if next_expiry is None:
            raise ValueError(f"No next monthly expiry found after {current} - update monthly_expiry_2026.json")
        return next_expiry
    return current


def get_monthly_expiry_string(today: date = None) -> str:
    """Returns expiry date formatted for Breeze API, e.g. '27-Jan-2026'."""
    return get_monthly_expiry_date(today).strftime("%d-%b-%Y")
