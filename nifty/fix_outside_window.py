import ast, sys

path = '/opt/smb-algo/webhooks/utlrg.py'
content = open(path).read()

old = '''    # ── Check trading window ─────────────────────────────────────────────────
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

new = '''    # ── Check trading window ─────────────────────────────────────────────────
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
        return {"status": "stored", "signal": signal, "message": msg}'''

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
print("Outside-window handler fixed — same direction signals ignored")
