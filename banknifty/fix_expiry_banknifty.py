import ast, sys

# ── Step 1: Append monthly expiry functions to expiry.py ─────────────────────
expiry_path = '/opt/smb-algo-bn/strategies/utlrg/expiry.py'
expiry_content = open(expiry_path).read()

monthly_code = '''

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
'''

new_expiry_content = expiry_content + monthly_code

try:
    ast.parse(new_expiry_content)
except SyntaxError as e:
    print(f"expiry.py SYNTAX ERROR: {e}")
    sys.exit(1)

open(expiry_path, 'w').write(new_expiry_content)
print("expiry.py: monthly functions appended, syntax OK")

# ── Step 2: Update import in order_router.py (alias trick) ───────────────────
router_path = '/opt/smb-algo-bn/core/order_router.py'
router_content = open(router_path).read()

old_import = "from strategies.utlrg.expiry import get_expiry_date, get_expiry_string"
new_import = "from strategies.utlrg.expiry import get_monthly_expiry_date as get_expiry_date, get_monthly_expiry_string as get_expiry_string"

if old_import not in router_content:
    print("order_router.py: import line not found — aborting (expiry.py already updated)")
    sys.exit(1)

new_router_content = router_content.replace(old_import, new_import)

try:
    ast.parse(new_router_content)
except SyntaxError as e:
    print(f"order_router.py SYNTAX ERROR: {e}")
    sys.exit(1)

open(router_path, 'w').write(new_router_content)
print("order_router.py: import aliased to monthly expiry functions, syntax OK")
print("Done.")
