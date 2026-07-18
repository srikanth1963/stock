import ast, sys

path = '/opt/smb-algo/core/order_router.py'
content = open(path).read()

# Add new function before eod_squareoff
old = '''async def eod_squareoff(strategy_id: str):'''

new = '''async def exit_only_if_reversed(strategy_id: str, signal: str):
    """
    Called when signal arrives outside trading window (post 3:00 PM).
    Exits existing position ONLY if signal is opposite direction.
    No new entry under any circumstance.
    Signal is already stored by caller.
    """
    accounts = get_active_accounts()
    today = date.today()
    for account in accounts:
        if is_trading_halted(account["name"], strategy_id, today):
            continue
        open_trade = get_open_trade(account["name"], strategy_id, today)
        if not open_trade:
            logger.info(f"[{strategy_id}][{account['name']}] Post-window signal {signal} — no open position")
            continue
        if open_trade["signal"] == signal:
            logger.info(f"[{strategy_id}][{account['name']}] Post-window signal {signal} — same direction as open trade, no action")
            continue
        logger.info(f"[{strategy_id}][{account['name']}] Post-window reversal — exiting #{open_trade['id']} immediately")
        await close_trade(open_trade, account, reason="SIGNAL_REVERSAL_POST_WINDOW")


async def eod_squareoff(strategy_id: str):'''

if old not in content:
    print("ERROR: pattern not found")
    sys.exit(1)

content = content.replace(old, new, 1)

try:
    ast.parse(content)
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

open(path, 'w').write(content)
print("core/order_router.py updated")
