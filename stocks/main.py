"""
main.py — SMB Algo Stocks FastAPI Application
Port: 8002
URL: trading.smbenablers.com/stocks/
"""

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import sqlalchemy

from database import (
    get_trade_db, TradeSession,
    Trade, Signal, AccountConfig, AccountStocks,
    StockMaster, DailyPnL, Holiday, ExpiryCalendar, ResultsCalendar
)
from breeze_client import get_breeze, refresh_session
from queue_manager import enqueue, clear_queue, queue_status
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from strike_selector import select_strike, StrikeSelectionError
from analytics import router as analytics_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app_state = {
    "trading_enabled": True,
    "account_status": {},
    "day_bias": __import__("json").load(open("/opt/smb-algo-stocks/config.json")).get("day_bias", "range") if __import__("os").path.exists("/opt/smb-algo-stocks/config.json") else "range",
}

WEBHOOK_SECRET = os.getenv("STOCKS_WEBHOOK_SECRET", "")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SMB Algo Stocks starting up...")
    try:
        get_breeze()
        logger.info("Breeze session ready")
    except Exception as e:
        logger.error(f"Breeze session failed at startup: {e}")

    db = TradeSession()
    try:
        accounts = db.query(AccountConfig).filter(AccountConfig.status == "Active").all()
        for acc in accounts:
            app_state["account_status"][acc.id] = {
                "enabled": True,
                "loss_limit_hit": False,
                "name": acc.account_name
            }
        logger.info(f"Loaded {len(accounts)} active accounts")
    finally:
        db.close()


    # Start scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(refresh_session, CronTrigger(hour=9, minute=0, second=0, timezone="Asia/Kolkata"), id="breeze_refresh")
    scheduler.add_job(morning_entry_job, CronTrigger(hour=9, minute=20, second=30, timezone="Asia/Kolkata"), id="morning_entry")
    scheduler.add_job(eod_squareoff_job, CronTrigger(hour=15, minute=18, second=0, timezone="Asia/Kolkata"), id="eod_squareoff")
    scheduler.add_job(_mtm_update_job, CronTrigger(hour="9-14", minute="*/5", timezone="Asia/Kolkata"), id="mtm_update")
    scheduler.start()
    app_state["scheduler"] = scheduler
    logger.info("Scheduler started with 3 jobs")
    yield
    # Stop scheduler
    if "scheduler" in app_state:
        app_state["scheduler"].shutdown()
        logger.info("Scheduler stopped")
    logger.info("SMB Algo Stocks shutting down...")


app = FastAPI(title="SMB Algo Stocks", lifespan=lifespan)
app.include_router(analytics_router, prefix="/stocks")


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_trading_day(db: Session) -> bool:
    today = date.today()
    if today.weekday() >= 5:
        return False
    return db.query(Holiday).filter(Holiday.holiday_date == today).first() is None


def is_result_window(ticker: str, db: Session) -> bool:
    today = date.today()
    for r in db.query(ResultsCalendar).filter(ResultsCalendar.nse_ticker == ticker).all():
        if abs((r.result_date - today).days) <= 1:
            return True
    return False


def get_current_expiry(db: Session) -> Optional[str]:
    today = date.today()
    expiries = db.query(ExpiryCalendar).filter(
        ExpiryCalendar.expiry_type == "MONTHLY",
        ExpiryCalendar.expiry_date >= today
    ).order_by(ExpiryCalendar.expiry_date).all()
    if not expiries:
        return None
    nearest = expiries[0]
    if (nearest.expiry_date - today).days <= 2 and len(expiries) > 1:
        nearest = expiries[1]
    return datetime.combine(nearest.expiry_date, datetime.min.time()).strftime("%Y-%m-%dT06:00:00.000Z")


def get_daily_loss(account_id: int, db: Session) -> float:
    pnl = db.query(DailyPnL).filter(
        DailyPnL.account_id == account_id,
        DailyPnL.date == date.today()
    ).first()
    if not pnl:
        return 0.0
    return min((pnl.realised_pnl or 0) + (pnl.unrealised_pnl or 0), 0)


def check_loss_limit(account_id: int, db: Session) -> bool:
    acc = db.query(AccountConfig).filter(AccountConfig.id == account_id).first()
    if not acc:
        return False
    return abs(get_daily_loss(account_id, db)) >= (acc.max_daily_loss or float('inf'))


def get_open_trade(account_id: int, ticker: str, db: Session) -> Optional[Trade]:
    return db.query(Trade).filter(
        Trade.account_id == account_id,
        Trade.nse_ticker == ticker,
        Trade.status == "OPEN"
    ).first()


def is_entry_allowed() -> bool:
    import pytz
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    cutoff = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return now < cutoff


def _ensure_daily_pnl(account_id: int, db: Session):
    today = date.today()
    if not db.query(DailyPnL).filter(
        DailyPnL.account_id == account_id, DailyPnL.date == today
    ).first():
        db.add(DailyPnL(account_id=account_id, date=today))
        db.commit()


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.post("/stocks/webhook/utlrg")
async def webhook_utlrg(request: Request, secret: str = "", db: Session = Depends(get_trade_db)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    secret = body.get("secret", "") or secret
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    ticker    = body.get("ticker", "").strip().upper()
    direction = body.get("direction", "").strip().upper()
    price     = float(body.get("price", 0))

    if not ticker or direction not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Invalid ticker or direction")

    # Market hours check: 9:15 AM - 3:30 PM IST only
    from datetime import timezone
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (market_open <= now_ist <= market_close):
        logger.info(f"Webhook rejected outside market hours: {ticker} {direction} @ {price}")
        return {"status": "ignored", "reason": "outside market hours"}
    logger.info(f"Webhook received: {ticker} {direction} @ {price}")

    if not is_trading_day(db):
        _store_signal_all_accounts(ticker, direction, price, db)
        return {"status": "stored", "reason": "holiday"}

    results = []
    accounts = db.query(AccountConfig).filter(AccountConfig.status == "Active").all()
    for acc in accounts:
        result = await _process_signal(acc, ticker, direction, price, db)
        results.append({"account": acc.dp_name or acc.account_name, **result})

    return {"status": "processed", "results": results}


def _store_signal_all_accounts(ticker: str, direction: str, price: float, db: Session):
    _upsert_signal(ticker, direction, price, db)


def _upsert_signal(ticker: str, direction: str, price: float, db: Session):
    sig = db.query(Signal).filter(
        Signal.nse_ticker == ticker
    ).first()
    if sig:
        sig.direction    = direction
        sig.signal_price = price
        sig.received_at  = datetime.utcnow()
    else:
        db.add(Signal(
            nse_ticker=ticker,
            direction=direction, signal_price=price,
            received_at=datetime.utcnow()
        ))
    db.commit()


async def _process_signal(acc: AccountConfig, ticker: str, direction: str,
                           price: float, db: Session) -> dict:
    acc_id = acc.id

    if not db.query(AccountStocks).filter(
        AccountStocks.account_id == acc_id,
        AccountStocks.nse_ticker == ticker
    ).first():
        return {"status": "skipped", "reason": "not in account universe"}

    _upsert_signal(ticker, direction, price, db)

    acc_status = app_state["account_status"].get(acc_id, {})
    if not acc_status.get("enabled", True):
        return {"status": "stored", "reason": "account disabled"}

    if check_loss_limit(acc_id, db):
        return {"status": "stored", "reason": "loss limit breached"}

    if is_result_window(ticker, db):
        return {"status": "skipped", "reason": "result window"}

    open_trade = get_open_trade(acc_id, ticker, db)
    if open_trade:
        if open_trade.direction == direction:
            return {"status": "ignored", "reason": "same direction trade open"}
        else:
            if not is_entry_allowed():
                # After 3PM: exit immediately, store signal, no new entry
                logger.info(f"[{acc.account_name}] Post-3PM reversal {ticker}: exiting, no new entry")
                await enqueue(acc_id, _execute_exit, open_trade.id, "SIGNAL_REVERSAL_POST3PM", acc_id)
                return {"status": "queued", "reason": "post 3PM reversal exit queued"}
            logger.info(f"[{acc.account_name}] Signal reversal {ticker}")
            await enqueue(acc_id, _execute_exit, open_trade.id, "SIGNAL_REVERSAL", acc_id)
            # Only enter new trade if bias allows
            bias = app_state.get("day_bias", "range").lower()
            if bias == "no_trade" or (bias == "bullish" and direction == "SELL") or (bias == "bearish" and direction == "BUY"):
                logger.info(f"[{acc.account_name}] Bias={bias.upper()} blocks reversal entry for {ticker}")
                return {"status": "queued", "reason": "reversal exit only, bias blocks new entry"}
            await enqueue(acc_id, _execute_entry, acc_id, ticker, direction, True)
            return {"status": "queued", "reason": "signal reversal"}

    if not is_entry_allowed():
        return {"status": "stored", "reason": "post 3PM no entry"}

    # Day Bias filter
    bias = app_state.get("day_bias", "range").lower()
    if bias == "no_trade":
        logger.info(f"[{acc.account_name}] Bias=NO_TRADE — skipping entry {ticker}")
        return {"status": "skipped", "reason": "day bias no_trade"}
    elif bias == "bullish" and direction == "SELL":
        logger.info(f"[{acc.account_name}] Bias=BULLISH — skipping SELL {ticker}")
        return {"status": "skipped", "reason": "day bias bullish blocks sell"}
    elif bias == "bearish" and direction == "BUY":
        logger.info(f"[{acc.account_name}] Bias=BEARISH — skipping BUY {ticker}")
        return {"status": "skipped", "reason": "day bias bearish blocks buy"}

    open_count = db.query(Trade).filter(
        Trade.account_id == acc_id, Trade.status == "OPEN"
    ).count()
    if open_count >= 25:
        return {"status": "queued_pending", "reason": "at concurrent trade limit"}

    await enqueue(acc_id, _execute_entry, acc_id, ticker, direction)
    return {"status": "queued", "reason": "fresh entry"}


# ── Trade execution — uses own DB session (fixes DetachedInstanceError) ────────

async def _execute_entry(account_id: int, ticker: str, direction: str, is_reversal: bool = False):
    """Execute entry order. Creates own DB session — safe for async queue."""
    db = TradeSession()
    try:
        acc = db.query(AccountConfig).filter(AccountConfig.id == account_id).first()
        if not acc:
            logger.error(f"Account {account_id} not found")
            return

        logger.info(f"[{acc.dp_name or acc.account_name}] Executing entry: {ticker} {direction}")

        stock = db.query(StockMaster).filter(StockMaster.nse_ticker == ticker).first()
        if not stock:
            logger.error(f"Stock {ticker} not found in master")
            return

        expiry_str = get_current_expiry(db)
        if not expiry_str:
            logger.error(f"No expiry found for {ticker}")
            return

        breeze = get_breeze()
        result = select_strike(
            breeze=breeze,
            breeze_code=stock.breeze_code,
            expiry_date=expiry_str,
            direction=direction,
            window=4
        )

        if acc.order_price_type == "aggressive":
            order_price = result["selected_ask"] if direction == "BUY" else result["selected_bid"]
        elif acc.order_price_type == "mid":
            order_price = round((result["selected_bid"] + result["selected_ask"]) / 2, 2)
        else:
            order_price = result["selected_bid"] if direction == "BUY" else result["selected_ask"]

        quantity    = stock.lot_size * (acc.lots_per_trade or 1)
        option_type = "CE" if direction == "BUY" else "PE"

        # Capital discipline check (skip for reversals)
        capital = acc.capital_allocation or 0
        if capital > 0 and not is_reversal:
            open_trades = db.query(Trade).filter(Trade.account_id == account_id, Trade.status == "OPEN").all()
            total_deployed = sum((t.entry_price or 0) * t.quantity for t in open_trades)
            new_investment = order_price * quantity
            if total_deployed > capital * 0.90:
                logger.info(f"[{acc.dp_name or acc.account_name}] Capital limit: deployed ₹{total_deployed:.0f} > 90% of ₹{capital:.0f} — skipping {ticker}")
                return
            if total_deployed + new_investment > capital:
                logger.info(f"[{acc.dp_name or acc.account_name}] Capital limit: deployed ₹{total_deployed:.0f} + new ₹{new_investment:.0f} > ₹{capital:.0f} — skipping {ticker}")
                return
        right       = "call" if direction == "BUY" else "put"
        expiry_breeze = datetime.strptime(expiry_str[:10], "%Y-%m-%d").strftime("%Y-%m-%dT06:00:00.000Z")

        # Paper mode — skip real order
        paper = bool(acc.paper_trading if acc.paper_trading is not None else 1)
        if paper:
            logger.info(f"[{acc.dp_name or acc.account_name}] PAPER: {ticker} {direction} "
                        f"{result['selected_strike']} {option_type} @ {order_price}")
            order_id = "PAPER"
        else:
            resp = breeze.place_order(
                stock_code=stock.breeze_code,
                exchange_code="NFO",
                product="options",
                action="buy",
                order_type="limit",
                stoploss="0",
                quantity=str(quantity),
                price=str(order_price),
                validity="day",
                validity_date=datetime.now().strftime("%Y-%m-%dT06:00:00.000Z"),
                disclosed_quantity="0",
                expiry_date=expiry_breeze,
                right=right,
                strike_price=str(result["selected_strike"]),
                user_remark="SMB-" + ticker + "-" + direction
            )
            if resp.get("Status") != 200:
                logger.error(f"Order placement failed for {ticker}: {resp.get('Error')}")
                return
            order_id = resp.get("Success", {}).get("order_id", "")

        expiry_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
        trade = Trade(
            account_id=account_id,
            trade_date=date.today(),
            nse_ticker=ticker,
            breeze_code=stock.breeze_code,
            expiry_date=expiry_date,
            direction=direction,
            option_type=option_type,
            strike_price=result["selected_strike"],
            lots=acc.lots_per_trade or 1,
            lot_size=stock.lot_size,
            quantity=quantity,
            entry_price=order_price,
            entry_time=datetime.utcnow(),
            status="OPEN",
            order_id=order_id,
            current_ltp=result["selected_ltp"]
        )
        db.add(trade)
        _ensure_daily_pnl(account_id, db)
        pnl_rec = db.query(DailyPnL).filter(
            DailyPnL.account_id == account_id, DailyPnL.date == date.today()
        ).first()
        if pnl_rec:
            pnl_rec.total_trades = (pnl_rec.total_trades or 0) + 1
        db.commit()
        logger.info(f"[{acc.dp_name or acc.account_name}] Entry done: {ticker} "
                    f"{result['selected_strike']} {option_type} @ {order_price} OI={result['selected_oi']}")

    except StrikeSelectionError as e:
        logger.error(f"Strike selection failed for {ticker}: {e}")
    except Exception as e:
        logger.error(f"Entry execution error for {ticker}: {e}")
    finally:
        db.close()


async def _execute_exit(trade_id: int, reason: str, account_id: int):
    """Execute exit order. Creates own DB session — safe for async queue."""
    db = TradeSession()
    try:
        acc   = db.query(AccountConfig).filter(AccountConfig.id == account_id).first()
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade or trade.status != "OPEN":
            return

        acc_name = acc.dp_name or acc.account_name if acc else str(account_id)
        logger.info(f"[{acc_name}] Executing exit: {trade.nse_ticker} reason={reason}")

        paper = bool(acc.paper_trading if acc and acc.paper_trading is not None else 1)
        right = "call" if trade.option_type == "CE" else "put"
        expiry_str = datetime.combine(
            trade.expiry_date, datetime.min.time()
        ).strftime("%Y-%m-%dT06:00:00.000Z")

        import asyncio as _asyncio
        deadline = datetime.now().replace(hour=15, minute=22, second=0, microsecond=0)

        if paper:
            exit_price = trade.current_ltp or trade.entry_price
            logger.info(f"PAPER exit: {trade.nse_ticker} @ {exit_price}")
        else:
            breeze = get_breeze()
            placed = False
            attempt = 0
            while True:
                attempt += 1
                now = datetime.now()
                try:
                    resp = breeze.get_quotes(
                        stock_code=trade.breeze_code,
                        exchange_code="NFO",
                        product_type="options",
                        expiry_date=expiry_str,
                        right=right,
                        strike_price=str(trade.strike_price)
                    )
                    exit_price = trade.current_ltp or trade.entry_price
                    if resp.get("Status") == 200:
                        rows = resp.get("Success") or []
                        if rows:
                            bid = float(rows[0].get("best_bid_price", 0) or 0)
                            ltp = float(rows[0].get("ltp", exit_price) or exit_price)
                            if bid > 0:
                                exit_price = bid
                            else:
                                exit_price = round(ltp * 0.95, 2)  # 5% below LTP
                    elif now >= deadline:
                        # After 3:22 PM force close at LTP - 5%
                        exit_price = round((trade.current_ltp or trade.entry_price) * 0.95, 2)
                        logger.warning(f"Post-3:22 force exit: {trade.nse_ticker} @ {exit_price}")
                except Exception as eq:
                    exit_price = round((trade.current_ltp or trade.entry_price) * 0.95, 2)
                    logger.warning(f"Quote fetch failed attempt {attempt}: {eq}. Using {exit_price}")

                try:
                    resp2 = breeze.place_order(
                        stock_code=trade.breeze_code,
                        exchange_code="NFO",
                        product="options",
                        action="sell",
                        order_type="limit",
                        stoploss="0",
                        quantity=str(trade.quantity),
                        price=str(exit_price),
                        validity="day",
                        validity_date=datetime.now().strftime("%Y-%m-%dT06:00:00.000Z"),
                        disclosed_quantity="0",
                        expiry_date=expiry_str,
                        right=right,
                        strike_price=str(trade.strike_price),
                        user_remark="SMB-EXIT-" + reason
                    )
                    if resp2.get("Status") == 200:
                        placed = True
                        break
                    else:
                        logger.warning(f"Exit order failed attempt {attempt} for {trade.nse_ticker}: {resp2.get('Error')}")
                except Exception as oe:
                    logger.warning(f"Exit order exception attempt {attempt}: {oe}")

                if datetime.now() >= deadline:
                    logger.error(f"Exit deadline passed for {trade.nse_ticker} after {attempt} attempts")
                    break
                await _asyncio.sleep(10)

            if not placed and datetime.now() >= deadline:
                # Force close in DB after deadline
                exit_price = round((trade.current_ltp or trade.entry_price) * 0.95, 2)
                logger.warning(f"Force closing {trade.nse_ticker} in DB at {exit_price}")

        pnl             = (exit_price - trade.entry_price) * trade.quantity
        trade.exit_price  = exit_price
        trade.exit_time   = datetime.utcnow()
        trade.exit_reason = reason
        trade.pnl         = pnl
        trade.status      = "CLOSED"

        daily = db.query(DailyPnL).filter(
            DailyPnL.account_id == account_id, DailyPnL.date == date.today()
        ).first()
        if daily:
            daily.realised_pnl   = (daily.realised_pnl or 0) + pnl
            daily.unrealised_pnl = (daily.unrealised_pnl or 0) - pnl

        db.commit()
        logger.info(f"[{acc_name}] Exit done: {trade.nse_ticker} PnL={pnl:.2f} reason={reason}")

        if check_loss_limit(account_id, db):
            await _trigger_loss_limit(account_id, db)

    except Exception as e:
        logger.error(f"Exit execution error: {e}")
    finally:
        db.close()


async def _trigger_loss_limit(account_id: int, db: Session):
    logger.warning(f"LOSS LIMIT TRIGGERED for account {account_id}")
    app_state["account_status"][account_id]["loss_limit_hit"] = True
    app_state["account_status"][account_id]["enabled"] = False
    await clear_queue(account_id)

    open_trades = db.query(Trade).filter(
        Trade.account_id == account_id, Trade.status == "OPEN"
    ).all()
    for trade in open_trades:
        await enqueue(account_id, _execute_exit, trade.id, "LOSS_LIMIT", account_id)

    daily = db.query(DailyPnL).filter(
        DailyPnL.account_id == account_id, DailyPnL.date == date.today()
    ).first()
    if daily:
        daily.loss_limit_breached = 1
        db.commit()


# ── Scheduler jobs ────────────────────────────────────────────────────────────


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

async def morning_entry_job():
    db = TradeSession()
    try:
        if not is_trading_day(db):
            return
        logger.info("Morning entry job triggered at 9:20:30")
        cutoff = datetime.now().replace(hour=9, minute=20, second=0, microsecond=0)
        for acc in db.query(AccountConfig).filter(AccountConfig.status == "Active").all():
            if not app_state["account_status"].get(acc.id, {}).get("enabled", True):
                continue
            for sig in db.query(Signal).all():
                # Skip if stock not in current universe
                if not db.query(AccountStocks).filter(
                    AccountStocks.account_id == acc.id,
                    AccountStocks.nse_ticker == sig.nse_ticker
                ).first():
                    continue
                if sig.received_at and sig.received_at.replace(tzinfo=None) > cutoff:
                    continue
                if get_open_trade(acc.id, sig.nse_ticker, db):
                    continue
                if is_result_window(sig.nse_ticker, db):
                    continue
                # Day Bias filter
                bias = app_state.get("day_bias", "range").lower()
                if bias == "no_trade":
                    continue
                if bias == "bullish" and sig.direction == "SELL":
                    continue
                if bias == "bearish" and sig.direction == "BUY":
                    continue
                logger.info(f"[{acc.account_name}] Queuing stored signal: {sig.nse_ticker} {sig.direction}")
                await enqueue(acc.id, _execute_entry, acc.id, sig.nse_ticker, sig.direction)
    finally:
        db.close()


async def eod_squareoff_job():
    db = TradeSession()
    try:
        if not is_trading_day(db):
            return
        logger.info("EOD squareoff job triggered at 3:18 PM")
        app_state["day_bias"] = "range"
        logger.info("Day bias reset to RANGE for next session")
        for acc in db.query(AccountConfig).filter(AccountConfig.status == "Active").all():
            open_trades = db.query(Trade).filter(
                Trade.account_id == acc.id, Trade.status == "OPEN"
            ).all()
            for trade in open_trades:
                await enqueue(acc.id, _execute_exit, trade.id, "EOD_SQUAREOFF", acc.id)
            logger.info(f"[{acc.account_name}] EOD: {len(open_trades)} positions queued")
    finally:
        db.close()


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/stocks/api/status")
async def get_status():
    return {
        "status": "ok",
        "trading_enabled": app_state["trading_enabled"],
        "accounts": app_state["account_status"],
        "queues": queue_status(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/stocks/api/dashboard")
async def get_dashboard(db: Session = Depends(get_trade_db)):
    accounts_data = []
    for acc in db.query(AccountConfig).all():
        daily = db.query(DailyPnL).filter(
            DailyPnL.account_id == acc.id, DailyPnL.date == date.today()
        ).first()
        positions = db.query(Trade).filter(
            Trade.account_id == acc.id, Trade.status == "OPEN"
        ).order_by(Trade.entry_time.desc()).all()
        pos_list = [{
            "id": t.id,
            "ticker": t.nse_ticker,
            "strike": t.strike_price,
            "option_type": t.option_type,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "current_ltp": t.current_ltp,
            "pnl": round(((t.current_ltp or t.entry_price) - t.entry_price) * t.quantity, 2),
            "quantity": t.quantity,
            "lots": t.lots,
            "lot_size": t.lot_size,
            "contract_value": round(t.entry_price * t.quantity, 2),
            "roi": round(((t.current_ltp or t.entry_price) - t.entry_price) / t.entry_price * 100, 2) if t.entry_price else 0,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None
        } for t in positions]
        acc_status = app_state["account_status"].get(acc.id, {})
        accounts_data.append({
            "id": acc.id,
            "name": acc.dp_name or acc.account_name,
            "broker": "ICICIDirect",
            "status": acc.status,
            "capital": acc.capital_allocation,
            "max_daily_loss": acc.max_daily_loss,
            "lots_per_trade": acc.lots_per_trade,
            "realised_pnl": daily.realised_pnl if daily else 0,
            "unrealised_pnl": daily.unrealised_pnl if daily else 0,
            "total_trades": daily.total_trades if daily else 0,
            "loss_limit_hit": acc_status.get("loss_limit_hit", False),
            "trading_enabled": acc_status.get("enabled", True),
            "paper_trading": bool(acc.paper_trading if acc.paper_trading is not None else 1),
            "total_deployed": round(sum((t.entry_price or 0) * t.quantity for t in positions), 2),
            "positions": pos_list
        })

    last_sig = db.query(Signal).order_by(Signal.received_at.desc()).first()

    nifty_mtm = 0
    bn_mtm    = 0
    try:
        import urllib.request, json as _json
        r = urllib.request.urlopen("http://localhost:8000/api/dashboard", timeout=2)
        d = _json.loads(r.read())
        nifty_mtm = sum(a.get("combined_pnl", 0) for a in (d.get("accounts") or []))
    except:
        pass
    try:
        import urllib.request, json as _json
        r = urllib.request.urlopen("http://localhost:8001/api/dashboard", timeout=2)
        d = _json.loads(r.read())
        bn_mtm = sum(a.get("combined_pnl", 0) for a in (d.get("accounts") or []))
    except:
        pass

    return {
        "time": datetime.now().isoformat(),
        "accounts": accounts_data,
        "last_signal": {
            "ticker": last_sig.nse_ticker,
            "direction": last_sig.direction,
            "received_at": last_sig.received_at.isoformat()
        } if last_sig else None,
        "system": {
            "webhook_active": True,
            "scheduler_running": True,
            "breeze_ok": True
        },
        "nifty_mtm": nifty_mtm,
        "bn_mtm": bn_mtm,
        "day_bias": app_state.get("day_bias", "range")
    }


@app.get("/stocks/api/trades")
async def get_trades(days: int = 7, account_id: Optional[int] = None,
                     db: Session = Depends(get_trade_db)):
    since  = date.today() - timedelta(days=days)
    query  = db.query(Trade).filter(Trade.trade_date >= since)
    if account_id:
        query = query.filter(Trade.account_id == account_id)
    trades = query.order_by(Trade.trade_date.desc(), Trade.entry_time.desc()).all()
    accounts = {a.id: a.dp_name or a.account_name for a in db.query(AccountConfig).all()}
    return {"trades": [{
        "id": t.id,
        "date": t.trade_date.isoformat(),
        "account": accounts.get(t.account_id, "Unknown"),
        "strategy": getattr(t, "strategy", "UTLRG"),
        "ticker": t.nse_ticker,
        "instrument": f"{t.nse_ticker} {int(t.strike_price)} {t.option_type}",
        "direction": t.direction,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "pnl": t.pnl,
        "exit_reason": t.exit_reason,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "status": t.status
    } for t in trades]}


@app.get("/stocks/api/account/{account_id}/stocks")
async def get_account_stocks(account_id: int, db: Session = Depends(get_trade_db)):
    stocks = db.query(AccountStocks).filter(AccountStocks.account_id == account_id).all()
    return {"tickers": [s.nse_ticker for s in stocks]}


@app.get("/stocks/api/positions")
async def get_positions(account_id: Optional[int] = None, db: Session = Depends(get_trade_db)):
    query  = db.query(Trade).filter(Trade.status == "OPEN")
    if account_id:
        query = query.filter(Trade.account_id == account_id)
    trades = query.all()
    return [{
        "id": t.id, "account_id": t.account_id, "ticker": t.nse_ticker,
        "direction": t.direction, "option_type": t.option_type,
        "strike": t.strike_price, "entry_price": t.entry_price,
        "current_ltp": t.current_ltp,
        "pnl": round(((t.current_ltp or t.entry_price) - t.entry_price) * t.quantity, 2),
        "quantity": t.quantity,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None
    } for t in trades]


@app.get("/stocks/api/pnl")
async def get_pnl(db: Session = Depends(get_trade_db)):
    today    = date.today()
    pnls     = db.query(DailyPnL).filter(DailyPnL.date == today).all()
    accounts = {a.id: a.dp_name or a.account_name for a in db.query(AccountConfig).all()}
    return [{
        "account_id": p.account_id,
        "account_name": accounts.get(p.account_id, "Unknown"),
        "realised_pnl": p.realised_pnl or 0,
        "unrealised_pnl": p.unrealised_pnl or 0,
        "total_pnl": (p.realised_pnl or 0) + (p.unrealised_pnl or 0),
        "total_trades": p.total_trades or 0,
        "loss_limit_breached": bool(p.loss_limit_breached)
    } for p in pnls]


@app.post("/stocks/api/exit/{trade_id}")
async def manual_exit(trade_id: int, db: Session = Depends(get_trade_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id, Trade.status == "OPEN").first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    await enqueue(trade.account_id, _execute_exit, trade_id, "MANUAL", trade.account_id)
    return {"status": "queued", "trade_id": trade_id}


@app.post("/stocks/api/kill_all")
async def kill_all(account_id: Optional[int] = None, db: Session = Depends(get_trade_db)):
    query  = db.query(Trade).filter(Trade.status == "OPEN")
    if account_id:
        query = query.filter(Trade.account_id == account_id)
    trades = query.all()
    for trade in trades:
        await enqueue(trade.account_id, _execute_exit, trade.id, "KILL_ALL", trade.account_id)
    return {"status": "queued", "trades_queued": len(trades)}


@app.post("/stocks/api/restart")
async def restart_trading(account_id: int):
    if account_id in app_state["account_status"]:
        app_state["account_status"][account_id]["enabled"] = True
        app_state["account_status"][account_id]["loss_limit_hit"] = False
        logger.info(f"Trading restarted for account {account_id}")
        return {"status": "restarted", "account_id": account_id}
    raise HTTPException(status_code=404, detail="Account not found")


@app.post("/stocks/api/account/{account_id}/paper_mode")
async def toggle_paper_mode(account_id: int, db: Session = Depends(get_trade_db)):
    acc = db.query(AccountConfig).filter(AccountConfig.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    current  = bool(acc.paper_trading if acc.paper_trading is not None else 1)
    new_mode = not current
    db.execute(
        sqlalchemy.text("UPDATE account_config SET paper_trading = :val WHERE id = :id"),
        {"val": 1 if new_mode else 0, "id": account_id}
    )
    db.commit()
    logger.info(f"Account {account_id} switched to {'Paper' if new_mode else 'LIVE'} trading")
    return {"status": "ok", "account_id": account_id, "paper_trading": new_mode}


@app.post("/stocks/api/day_bias")
async def set_day_bias(request: Request):
    """Set day bias: range / bullish / bearish / no_trade"""
    body = await request.json()
    bias = body.get("bias", "range").lower()
    if bias not in ("range", "bullish", "bearish", "no_trade"):
        raise HTTPException(status_code=400, detail="Invalid bias value")
    app_state["day_bias"] = bias
    import json as _json
    _json.dump({"day_bias": bias}, open("/opt/smb-algo-stocks/config.json", "w"))
    logger.info(f"Day bias set to: {bias.upper()}")
    return {"status": "ok", "day_bias": bias}


@app.get("/stocks/api/day_bias")
async def get_day_bias():
    return {"day_bias": app_state.get("day_bias", "range")}


@app.post("/stocks/api/refresh_session")
async def refresh_breeze_session():
    success = refresh_session()
    return {"status": "ok" if success else "failed"}


@app.post("/stocks/api/pull_gsheet")
async def pull_gsheet():
    try:
        result = subprocess.run(
            ["python3", "/opt/smb-algo-stocks/gsheet_pull.py"],
            capture_output=True, text=True, timeout=120
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "output": result.stdout,
            "error": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/stocks/api/refresh_master")
async def refresh_security_master():
    try:
        dl = subprocess.run(
            ["wget", "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip",
             "-O", "/tmp/SecurityMaster.zip", "-q"],
            capture_output=True, timeout=60
        )
        if dl.returncode != 0:
            return {"status": "error", "error": "Download failed"}
        subprocess.run(
            ["python3", "-c",
             "import zipfile; zipfile.ZipFile('/tmp/SecurityMaster.zip').extractall('/tmp/secmaster/')"],
            timeout=30
        )
        return {"status": "ok", "message": "Master downloaded successfully."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/stocks/", response_class=HTMLResponse)
async def dashboard_landing():
    html_path = "/opt/smb-algo-stocks/index.html"
    if os.path.exists(html_path):
        return HTMLResponse(open(html_path).read())
    return HTMLResponse("<h1>SMB Algo Stocks</h1><p>Dashboard loading...</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
