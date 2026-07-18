"""
Adds APScheduler with MTM, morning entry, and EOD squareoff jobs to main.py
"""
lines = open('/opt/smb-algo-stocks/main.py').readlines()

# Find the line numbers we need
lifespan_start = None
yield_line = None
for i, line in enumerate(lines):
    if 'async def lifespan(app: FastAPI):' in line:
        lifespan_start = i
    if '    yield' in line and lifespan_start and i > lifespan_start:
        yield_line = i
        break

print(f"lifespan starts at line {lifespan_start+1}, yield at line {yield_line+1}")

# Add import at top
import_line = None
for i, line in enumerate(lines):
    if 'from strike_selector import' in line:
        import_line = i
        break

scheduler_import = 'from apscheduler.schedulers.asyncio import AsyncIOScheduler\nfrom apscheduler.triggers.cron import CronTrigger\n'
lines.insert(import_line, scheduler_import)

# Recalculate yield_line after insertion
yield_line += 1

# Add scheduler start/stop around yield
scheduler_start = '''
    # Start scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(morning_entry_job, CronTrigger(hour=9, minute=20, second=30, timezone="Asia/Kolkata"), id="morning_entry")
    scheduler.add_job(eod_squareoff_job, CronTrigger(hour=15, minute=20, second=0, timezone="Asia/Kolkata"), id="eod_squareoff")
    scheduler.add_job(_mtm_update_job, CronTrigger(hour="9-14", minute="*/5", timezone="Asia/Kolkata"), id="mtm_update")
    scheduler.start()
    app_state["scheduler"] = scheduler
    logger.info("Scheduler started with 3 jobs")
'''

scheduler_stop = '''    # Stop scheduler
    if "scheduler" in app_state:
        app_state["scheduler"].shutdown()
        logger.info("Scheduler stopped")
'''

lines.insert(yield_line, scheduler_start)
yield_line += 1
lines.insert(yield_line + 1, scheduler_stop)

open('/opt/smb-algo-stocks/main.py', 'w').writelines(lines)

# Now add the MTM update job function
content = open('/opt/smb-algo-stocks/main.py').read()
mtm_job = '''
async def _mtm_update_job():
    """Update unrealised P&L for all open positions every 5 minutes."""
    db = TradeSession()
    try:
        if not is_trading_day(db):
            return
        breeze = get_breeze()
        open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
        for trade in open_trades:
            try:
                right = "call" if trade.option_type == "CE" else "put"
                expiry_str = datetime.combine(trade.expiry_date, datetime.min.time()).strftime("%Y-%m-%dT06:00:00.000Z")
                resp = breeze.get_quotes(
                    stock_code=trade.breeze_code,
                    exchange_code="NFO",
                    product_type="options",
                    expiry_date=expiry_str,
                    right=right,
                    strike_price=str(trade.strike_price)
                )
                if resp.get("Status") == 200:
                    rows = resp.get("Success") or []
                    if rows:
                        trade.current_ltp = float(rows[0].get("ltp", trade.current_ltp or 0))
            except Exception as e:
                logger.error(f"MTM update failed for trade {trade.id}: {e}")

        # Update unrealised P&L per account
        today = date.today()
        accounts = db.query(AccountConfig).filter(AccountConfig.status == "Active").all()
        for acc in accounts:
            acc_trades = [t for t in open_trades if t.account_id == acc.id]
            unrealised = sum(
                ((t.current_ltp or t.entry_price) - t.entry_price) * t.quantity
                for t in acc_trades
            )
            daily = db.query(DailyPnL).filter(
                DailyPnL.account_id == acc.id, DailyPnL.date == today
            ).first()
            if daily:
                daily.unrealised_pnl = unrealised
            if check_loss_limit(acc.id, db):
                if not app_state.get("account_status", {}).get(acc.id, {}).get("loss_limit_hit"):
                    await _trigger_loss_limit(acc.id, db)
        db.commit()
        logger.debug(f"MTM updated for {len(open_trades)} open trades")
    except Exception as e:
        logger.error(f"MTM update job error: {e}")
    finally:
        db.close()

'''

# Insert before morning_entry_job
content = content.replace('async def morning_entry_job():', mtm_job + 'async def morning_entry_job():')
open('/opt/smb-algo-stocks/main.py', 'w').write(content)

# Verify syntax
import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/opt/smb-algo-stocks/main.py'], capture_output=True)
if result.returncode == 0:
    print('Syntax OK — scheduler and MTM job added successfully')
else:
    print('Syntax ERROR:', result.stderr.decode())
