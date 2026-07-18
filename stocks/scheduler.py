"""
scheduler.py — APScheduler jobs for SMB Algo Stocks

Jobs:
- 9:20:30 AM  — Morning entry (stored signals)
- 3:20:00 PM  — EOD squareoff
- Every 5 min — MTM update (unrealised P&L)
- 8:15 AM     — Security master refresh (expiry+1 only)
"""

import logging
from datetime import date, datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def create_scheduler(app_state: dict) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    # Morning entry at 9:20:30
    scheduler.add_job(
        _morning_entry_wrapper,
        CronTrigger(hour=9, minute=20, second=30, timezone="Asia/Kolkata"),
        id="morning_entry",
        name="Morning Entry Job",
        args=[app_state]
    )

    # EOD squareoff at 3:20 PM
    scheduler.add_job(
        _eod_squareoff_wrapper,
        CronTrigger(hour=15, minute=20, second=0, timezone="Asia/Kolkata"),
        id="eod_squareoff",
        name="EOD Squareoff Job",
        args=[app_state]
    )

    # MTM update every 5 minutes during market hours
    scheduler.add_job(
        _mtm_update_wrapper,
        CronTrigger(
            hour="9-14", minute="*/5",
            timezone="Asia/Kolkata"
        ),
        id="mtm_update",
        name="MTM Update Job",
        args=[app_state]
    )

    logger.info("Scheduler configured with 3 jobs")
    return scheduler


async def _morning_entry_wrapper(app_state: dict):
    """Wrapper to call morning_entry_job from main.py with fresh DB session."""
    try:
        from database import TradeSession
        from main import morning_entry_job, is_trading_day
        db = TradeSession()
        if is_trading_day(db):
            await morning_entry_job(db)
        db.close()
    except Exception as e:
        logger.error(f"Morning entry job error: {e}")


async def _eod_squareoff_wrapper(app_state: dict):
    """Wrapper to call eod_squareoff_job from main.py with fresh DB session."""
    try:
        from database import TradeSession
        from main import eod_squareoff_job, is_trading_day
        db = TradeSession()
        if is_trading_day(db):
            await eod_squareoff_job(db)
        db.close()
    except Exception as e:
        logger.error(f"EOD squareoff job error: {e}")


async def _mtm_update_wrapper(app_state: dict):
    """Update unrealised P&L for all open positions."""
    try:
        from database import TradeSession
        from main import is_trading_day, get_current_expiry
        from breeze_client import get_breeze
        db = TradeSession()

        if not is_trading_day(db):
            db.close()
            return

        from database import Trade, DailyPnL, AccountConfig
        breeze = get_breeze()

        open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
        for trade in open_trades:
            try:
                right = "call" if trade.option_type == "CE" else "put"
                expiry_str = datetime.combine(
                    trade.expiry_date, datetime.min.time()
                ).strftime("%Y-%m-%dT06:00:00.000Z")

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
                        ltp = float(rows[0].get("ltp", trade.current_ltp or 0))
                        trade.current_ltp = ltp

            except Exception as e:
                logger.error(f"MTM update failed for trade {trade.id}: {e}")

        # Update unrealised P&L per account
        accounts = db.query(AccountConfig).filter(AccountConfig.status == "Active").all()
        today = date.today()

        for acc in accounts:
            acc_trades = [t for t in open_trades if t.account_id == acc.id]
            unrealised = sum(
                ((t.current_ltp or t.entry_price) - t.entry_price) * t.quantity
                for t in acc_trades
            )

            daily = db.query(DailyPnL).filter(
                DailyPnL.account_id == acc.id,
                DailyPnL.date == today
            ).first()
            if daily:
                daily.unrealised_pnl = unrealised
                daily.updated_at = datetime.utcnow()

            # Check loss limit
            from main import check_loss_limit, _trigger_loss_limit
            if check_loss_limit(acc.id, db):
                if not app_state.get("account_status", {}).get(acc.id, {}).get("loss_limit_hit"):
                    logger.warning(f"[{acc.account_name}] Loss limit breached during MTM check")
                    await _trigger_loss_limit(acc, db)

        db.commit()
        db.close()

    except Exception as e:
        logger.error(f"MTM update job error: {e}")
