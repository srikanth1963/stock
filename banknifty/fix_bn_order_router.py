"""
Fix BankNifty order_router.py:
1. Add get_instrument(strategy_id) helper reading from strategies.json
2. Replace all hardcoded "NIFTY" with get_instrument(strategy_id)
3. Add exit_only_if_reversed (copy from NIFTY's fixed order_router.py)
"""
import ast, sys

# Copy NIFTY's fixed order_router as base (has exit_only_if_reversed already)
content = open('/opt/smb-algo/core/order_router.py').read()

# Step 1: Add get_instrument() helper alongside get_lot_size()
old_lot_size = '''def get_lot_size(strategy_id: str) -> int:
    """Read lot size from strategies.json. Never hardcoded."""
    try:
        data = json.load(open('/opt/smb-algo/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('lot_size', 65)
    except Exception as e:
        logger.warning(f"Could not read lot_size from config: {e}. Using 65.")
        return 65'''

new_lot_size = '''def get_lot_size(strategy_id: str) -> int:
    """Read lot size from strategies.json. Never hardcoded."""
    try:
        data = json.load(open('/opt/smb-algo-bn/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('lot_size', 30)
    except Exception as e:
        logger.warning(f"Could not read lot_size from config: {e}. Using 30.")
        return 30


def get_instrument(strategy_id: str) -> str:
    """Read instrument/symbol from strategies.json. Never hardcoded."""
    try:
        data = json.load(open('/opt/smb-algo-bn/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('instrument', 'BANKNIFTY')
    except Exception as e:
        logger.warning(f"Could not read instrument from config: {e}. Using BANKNIFTY.")
        return 'BANKNIFTY\''''

if old_lot_size not in content:
    print("ERROR: get_lot_size pattern not found")
    sys.exit(1)

content = content.replace(old_lot_size, new_lot_size, 1)

# Step 2: Replace hardcoded "NIFTY" in get_spot_price
content = content.replace(
    '    return await get_spot(account, "NIFTY")',
    '    return await get_spot(account, get_instrument(strategy_id))'
)

# Step 3: Replace hardcoded "NIFTY" in enter_trade log line
content = content.replace(
    'logger.info(f"[{strategy_id}][{name}] Entering {signal}: NIFTY {strike} {option_type.value} {expiry_str} | {lots}L={total_qty}u | {\'PAPER\' if account[\'paper_mode\'] else \'LIVE\'}")',
    'logger.info(f"[{strategy_id}][{name}] Entering {signal}: {get_instrument(strategy_id)} {strike} {option_type.value} {expiry_str} | {lots}L={total_qty}u | {\'PAPER\' if account[\'paper_mode\'] else \'LIVE\'}")'
)

# Step 4: Replace hardcoded "NIFTY" in Trade record instrument field
content = content.replace(
    '            instrument="NIFTY",',
    '            instrument=get_instrument(strategy_id),'
)

# Step 5: Replace hardcoded "NIFTY" in paper_fill
content = content.replace(
    '    ltp = await get_ltp(account, "NIFTY", strike, option_type, expiry_str)',
    '    ltp = await get_ltp(account, get_instrument(strategy_id), strike, option_type, expiry_str)'
)

# Step 6: Replace hardcoded "NIFTY" in update_mtm
content = content.replace(
    '        ltp = await get_ltp(account, "NIFTY", trade["strike"], trade["option_type"], trade["expiry_str"])',
    '        ltp = await get_ltp(account, get_instrument(strategy_id), trade["strike"], trade["option_type"], trade["expiry_str"])'
)

# Step 7: Replace hardcoded "NIFTY" in live_order
content = content.replace(
    '        logger.info(f"[{strategy_id}][{name}] Attempt {attempt}: {action} {quantity}u NIFTY {strike}{option_type} @ Rs.{limit_price}")',
    '        logger.info(f"[{strategy_id}][{name}] Attempt {attempt}: {action} {quantity}u {get_instrument(strategy_id)} {strike}{option_type} @ Rs.{limit_price}")'
)

# Step 8: Fix get_spot_price signature to accept strategy_id
old_spot = '''async def get_spot_price(account: dict) -> Optional[float]:
    from core.breeze_client import get_spot
    return await get_spot(account, get_instrument(strategy_id))'''

new_spot = '''async def get_spot_price(account: dict, strategy_id: str) -> Optional[float]:
    from core.breeze_client import get_spot
    return await get_spot(account, get_instrument(strategy_id))'''

content = content.replace(old_spot, new_spot, 1)

# Step 9: Fix enter_trade call to get_spot_price to pass strategy_id
content = content.replace(
    '        spot = await get_spot_price(account)',
    '        spot = await get_spot_price(account, strategy_id)'
)

# Verify no "NIFTY" hardcoded strings remain in critical sections
remaining = [line for line in content.split('\n') 
             if '"NIFTY"' in line and 'get_instrument' not in line 
             and '#' not in line.split('"NIFTY"')[0]]
if remaining:
    print("WARNING: remaining hardcoded NIFTY references:")
    for line in remaining:
        print(f"  {line.strip()}")

try:
    ast.parse(content)
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

open('/opt/smb-algo-bn/core/order_router.py', 'w').write(content)
print("BankNifty order_router.py updated — instrument reads from strategies.json")
