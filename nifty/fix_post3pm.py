import ast, sys

path = '/opt/smb-algo/webhooks/utlrg.py'
content = open(path).read()

old = '''    # ── Check trading window ─────────────────────────────────────────────────────
    if not is_within_trading_window():
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
        msg = f"Signal received at {now_ist} IST — outside trading window. Stored only."
        logger.info(f"[{STRATEGY_ID}] {msg}")
        # Still store the signal for carry-over — just don't trade
        save_signal(STRATEGY_ID, signal)
        log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=False, error=msg)
        return {"status": "stored", "signal": signal, "message": msg}'''

new = '''    # ── Check trading window ─────────────────────────────────────────────────────
    if not is_within_trading_window():
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
        msg = f"Signal received at {now_ist} IST — outside trading window. Stored only."
        logger.info(f"[{STRATEGY_ID}] {msg}")
        # Store signal for carry-over
        save_signal(STRATEGY_ID, signal)
        log_webhook(STRATEGY_ID, raw_str, signal=signal, processed=False, error=msg)
        # Exit-only: if signal is opposite to open position, square off immediately
        background_tasks.add_task(exit_only_if_reversed, STRATEGY_ID, signal)
        return {"status": "stored", "signal": signal, "message": msg}'''

if old not in content:
    print("ERROR: pattern not found")
    sys.exit(1)

# Add exit_only_if_reversed import at top of file
old_import = "from core.order_router import handle_signal"
new_import = "from core.order_router import handle_signal, exit_only_if_reversed"

if old_import not in content:
    print("ERROR: import pattern not found")
    sys.exit(1)

content = content.replace(old, new, 1)
content = content.replace(old_import, new_import, 1)

try:
    ast.parse(content)
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

open(path, 'w').write(content)
print("webhooks/utlrg.py updated")
