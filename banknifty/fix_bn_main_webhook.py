"""
Fix BankNifty main.py and webhooks/utlrg.py to match NIFTY's fixes:
1. Copy fixed main.py from NIFTY, change port to 8001
2. Copy fixed webhooks/utlrg.py from NIFTY, keep BN webhook secret env var
"""
import ast, sys

# ── Fix main.py ───────────────────────────────────────────────────────────────
nifty_main = open('/opt/smb-algo/main.py').read()

# Only difference: port 8001 instead of 8000
bn_main = nifty_main.replace(
    'uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)',
    'uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)'
)

if 'port=8001' not in bn_main:
    print("ERROR: port replacement failed")
    sys.exit(1)

try:
    ast.parse(bn_main)
except SyntaxError as e:
    print(f"main.py SYNTAX ERROR: {e}")
    sys.exit(1)

open('/opt/smb-algo-bn/main.py', 'w').write(bn_main)
print("BankNifty main.py updated (port=8001, 30s wait, clean duplicates)")

# ── Fix webhooks/utlrg.py ─────────────────────────────────────────────────────
nifty_webhook = open('/opt/smb-algo/webhooks/utlrg.py').read()

# BankNifty webhook file is identical to NIFTY's fixed version
# WEBHOOK_SECRET is read from os.getenv("WEBHOOK_SECRET") — already set in .env
# No other differences needed
try:
    ast.parse(nifty_webhook)
except SyntaxError as e:
    print(f"webhook SYNTAX ERROR: {e}")
    sys.exit(1)

open('/opt/smb-algo-bn/webhooks/utlrg.py', 'w').write(nifty_webhook)
print("BankNifty webhooks/utlrg.py updated (TRADING_START=9:20, same-direction check, exit_only_if_reversed)")

print("\nAll done. Now fix order_router.py instrument hardcoding separately.")
