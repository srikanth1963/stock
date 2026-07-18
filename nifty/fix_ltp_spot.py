"""
Add current_ltp and current_spot display:
1. order_router.py — save to DB in update_mtm()
2. api/routes.py — return in open_position response
3. frontend/index.html — display in position box
"""
import ast, sys

# ── Fix 1: order_router.py ────────────────────────────────────────────────────
path = '/opt/smb-algo/core/order_router.py'
content = open(path).read()

old = '''        mtm = (ltp - trade["entry_price"]) * trade["total_quantity"]
        with get_db() as db:
            r = db.query(DailyPnL).filter_by(
                account_name=account["name"],
                strategy_id=strategy_id,
                pnl_date=today
            ).first()
            if not r:
                r = DailyPnL(account_name=account["name"], strategy_id=strategy_id, pnl_date=today)
                db.add(r)
            r.mtm_pnl     = round(mtm, 2)
            r.combined_pnl = round((r.realised_pnl or 0) + mtm, 2)'''

new = '''        mtm = (ltp - trade["entry_price"]) * trade["total_quantity"]
        # Fetch current spot for display
        spot = await get_spot_price(account)
        with get_db() as db:
            # Update current_ltp on the open trade
            t = db.query(Trade).filter_by(id=trade["id"], exit_time=None).first()
            if t:
                t.current_ltp = round(ltp, 2)
            r = db.query(DailyPnL).filter_by(
                account_name=account["name"],
                strategy_id=strategy_id,
                pnl_date=today
            ).first()
            if not r:
                r = DailyPnL(account_name=account["name"], strategy_id=strategy_id, pnl_date=today)
                db.add(r)
            r.mtm_pnl     = round(mtm, 2)
            r.combined_pnl = round((r.realised_pnl or 0) + mtm, 2)
            if spot:
                r.current_spot = round(spot, 2)'''

if old not in content:
    print("ERROR: order_router pattern not found")
    sys.exit(1)
content = content.replace(old, new, 1)
try:
    ast.parse(content)
except SyntaxError as e:
    print(f"order_router SYNTAX ERROR: {e}")
    sys.exit(1)
open(path, 'w').write(content)
print("order_router.py updated")

# ── Fix 2: api/routes.py ──────────────────────────────────────────────────────
path = '/opt/smb-algo/api/routes.py'
content = open(path).read()

old = '''                    "entry_spot": open_trade.entry_spot,'''
new = '''                    "entry_spot": open_trade.entry_spot,
                    "current_ltp": open_trade.current_ltp,
                    "current_spot": pnl_record.current_spot if pnl_record else None,'''

if old not in content:
    print("ERROR: routes.py pattern not found")
    sys.exit(1)
content = content.replace(old, new, 1)
try:
    ast.parse(content)
except SyntaxError as e:
    print(f"routes.py SYNTAX ERROR: {e}")
    sys.exit(1)
open(path, 'w').write(content)
print("api/routes.py updated")

# ── Fix 3: frontend/index.html ────────────────────────────────────────────────
path = '/opt/smb-algo/frontend/index.html'
content = open(path).read()

old = "      e('div',null,e('div',{className:'pos-field-label'},'Entry Spot'),e('div',{className:'pos-field-value'},pos.entry_spot?`₹${pos.entry_spot}`:'—')),"
new = """      e('div',null,e('div',{className:'pos-field-label'},'Entry Spot'),e('div',{className:'pos-field-value'},pos.entry_spot?`₹${pos.entry_spot}`:'—')),
      e('div',null,e('div',{className:'pos-field-label'},'LTP'),e('div',{className:'pos-field-value'},pos.current_ltp?`₹${pos.current_ltp}`:'—')),
      e('div',null,e('div',{className:'pos-field-label'},'Spot Now'),e('div',{className:'pos-field-value'},pos.current_spot?`₹${pos.current_spot}`:'—')),"""

if old not in content:
    print("ERROR: frontend pattern not found")
    sys.exit(1)
content = content.replace(old, new, 1)
open(path, 'w').write(content)
print("frontend/index.html updated")

print("\nAll done!")
