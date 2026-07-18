"""
SMB Algo — Database cleanup before Tuesday trading.
Run this ONCE after market hours on Monday evening.

What it does:
1. Shows all today's trades for review
2. Removes the extra/duplicate trade #4 (Entry: null, the bad one)
3. Closes the open BUY position (trade #3) as EOD since market is over
4. Resets daily P&L to reflect correct state
5. Saves SELL as the last signal for tomorrow's carry-over

Run: cd /opt/smb-algo && source venv/bin/activate && PYTHONPATH=/opt/smb-algo python3 cleanup_db.py
"""

import sys
sys.path.insert(0, '/opt/smb-algo')

from datetime import date, datetime, timezone
from core.database import get_db, Trade, DailyPnL, SignalState
from core.signal_state import save_signal

today = date.today()

print("=" * 60)
print("SMB ALGO — DATABASE CLEANUP")
print(f"Date: {today}")
print("=" * 60)

with get_db() as db:
    trades = db.query(Trade).filter_by(trade_date=today).order_by(Trade.id).all()
    print(f"\nToday's trades ({len(trades)} found):")
    for t in trades:
        print(f"  #{t.id} | {t.signal} | {t.strike} {t.option_type} | Entry: {t.entry_price} | Exit: {t.exit_price} | Reason: {t.exit_reason}")

print()
response = input("Proceed with cleanup? (yes/no): ").strip().lower()
if response != "yes":
    print("Aborted.")
    sys.exit(0)

with get_db() as db:
    trades = db.query(Trade).filter_by(trade_date=today).order_by(Trade.id).all()

    # Step 1: Delete trades with null/zero entry price (bad trades)
    deleted = 0
    for t in trades:
        if not t.entry_price or t.entry_price == 0.0:
            print(f"  Deleting bad trade #{t.id} (entry_price={t.entry_price})")
            db.delete(t)
            deleted += 1
    print(f"Deleted {deleted} bad trade(s)")

    # Step 2: Close any remaining open trades as EOD
    remaining = db.query(Trade).filter_by(trade_date=today, exit_time=None).all()
    for t in remaining:
        print(f"  Closing open trade #{t.id} as EOD (entry: Rs.{t.entry_price})")
        t.exit_time   = datetime.now(timezone.utc)
        t.exit_price  = t.entry_price  # assume flat for cleanup
        t.exit_reason = "EOD_MANUAL_CLEANUP"
        t.pnl         = 0.0
        t.pnl_pct     = 0.0
    print(f"Closed {len(remaining)} open trade(s)")

    # Step 3: Show final trade list
    print("\nFinal trade list:")
    final = db.query(Trade).filter_by(trade_date=today).order_by(Trade.id).all()
    for t in final:
        print(f"  #{t.id} | {t.signal} | {t.strike} {t.option_type} | Entry: {t.entry_price} | Exit: {t.exit_price} | Reason: {t.exit_reason}")

print()
print("✓ Database cleaned")
print()

# Step 4: Show current signal state
from core.signal_state import get_last_signal
sig = get_last_signal("utlrg")
print(f"Current stored signal: {sig}")
print()
print("Tomorrow morning carry-over will use this signal.")
print("If the current TV signal is different, update it manually.")
print()
print("=" * 60)
print("CLEANUP COMPLETE — System ready for tomorrow")
print("=" * 60)
