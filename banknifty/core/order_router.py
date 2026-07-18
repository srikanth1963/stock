"""
SMB Algo — Order Router v2
Complete rewrite fixing all known issues:
1. DetachedInstanceError: get_open_trade returns dict, not ORM object
2. close_trade accepts dict, never touches ORM outside session
3. Expiry format consistent: "16-Jun-2026" (not upper case)
4. MTM uses dict approach
5. eod_squareoff uses dict approach
"""

import logging
import asyncio
import json
from datetime import datetime, timezone, date
from typing import Optional
from zoneinfo import ZoneInfo

from core.database import get_db, Trade, DailyPnL
from core.accounts import get_active_accounts
from strategies.utlrg.strike import get_itm_strike, get_option_type, Signal
from strategies.utlrg.expiry import get_monthly_expiry_date as get_expiry_date, get_monthly_expiry_string as get_expiry_string

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
CANDLE_WAIT_SECONDS = 0


# ── Pure helper functions (no ORM objects ever leave these) ───────────────────

def get_lot_size(strategy_id: str) -> int:
    """Read lot size from strategies.json. Never hardcoded."""
    try:
        data = json.load(open('/opt/smb-algo-bn/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('lot_size', 30)
    except Exception as e:
        logger.warning(f"Could not read lot_size from config: {e}. Using 30.")
        return 30

def get_day_bias(strategy_id: str) -> str:
    """Read day_bias from strategies.json."""
    try:
        data = json.load(open('/opt/smb-algo-bn/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('day_bias', 'range').lower()
    except Exception as e:
        logger.warning(f'Could not read day_bias: {e}. Using range.')
        return 'range'



def get_instrument(strategy_id: str) -> str:
    """Read instrument/symbol from strategies.json. Never hardcoded."""
    try:
        data = json.load(open('/opt/smb-algo-bn/config/strategies.json'))
        cfg = next((s for s in data['strategies'] if s['id'] == strategy_id), {})
        return cfg.get('instrument', 'BANKNIFTY')
    except Exception as e:
        logger.warning(f"Could not read instrument from config: {e}. Using BANKNIFTY.")
        return 'BANKNIFTY'


def get_open_trade(account_name: str, strategy_id: str, trade_date: date) -> Optional[dict]:
    """
    Returns today's open trade as a PLAIN DICT.
    ORM objects NEVER leave this function — eliminates DetachedInstanceError.
    """
    with get_db() as db:
        t = db.query(Trade).filter_by(
            account_name=account_name,
            strategy_id=strategy_id,
            trade_date=trade_date,
            exit_time=None
        ).first()
        if t is None:
            return None
        # Extract all needed fields while session is open
        return {
            "id":             t.id,
            "signal":         t.signal,
            "strike":         t.strike,
            "option_type":    t.option_type,
            "expiry_str":     t.expiry_date.strftime("%d-%b-%Y"),  # "16-Jun-2026"
            "quantity_lots":  t.quantity_lots,
            "lot_size":       t.lot_size,
            "total_quantity": t.total_quantity,
            "entry_price":    t.entry_price or 0.0,
            "strategy_id":    t.strategy_id,
            "account_name":   t.account_name,
            "preclosure_done": t.preclosure_done or False,
            "remaining_lots":  t.remaining_lots,
        }


def is_trading_halted(account_name: str, strategy_id: str, trade_date: date) -> bool:
    with get_db() as db:
        r = db.query(DailyPnL).filter_by(
            account_name=account_name,
            strategy_id=strategy_id,
            pnl_date=trade_date
        ).first()
        return r.trading_halted if r else False


def update_daily_pnl(account_name: str, strategy_id: str, pnl_delta: float):
    from core.accounts import get_account
    account = get_account(account_name)
    today = date.today()
    with get_db() as db:
        r = db.query(DailyPnL).filter_by(
            account_name=account_name,
            strategy_id=strategy_id,
            pnl_date=today
        ).first()
        if not r:
            r = DailyPnL(account_name=account_name, strategy_id=strategy_id, pnl_date=today)
            db.add(r)
        r.realised_pnl = round((r.realised_pnl or 0) + pnl_delta, 2)
        r.combined_pnl = round((r.realised_pnl or 0) + (r.mtm_pnl or 0), 2)
        r.trade_count = (r.trade_count or 0) + 1
        loss_limit = account.get("daily_loss_limit", 0) if account else 0
        if loss_limit and r.combined_pnl <= -abs(loss_limit):
            r.trading_halted = True
            r.halt_reason = "DAILY_LOSS_LIMIT"
            logger.warning(f"[{account_name}] LOSS LIMIT BREACHED: Rs.{r.combined_pnl}")


async def get_spot_price(account: dict, strategy_id: str) -> Optional[float]:
    from core.breeze_client import get_spot
    for attempt in range(1, 4):
        spot = await get_spot(account, get_instrument(strategy_id))
        if spot:
            return spot
        if attempt < 3:
            import asyncio as _asyncio
            await _asyncio.sleep(2)
    return None


# ── Core trading functions ────────────────────────────────────────────────────

async def handle_signal(strategy_id: str, signal: str, tv_spot: float = None):
    """Entry point from webhook. Waits for next candle then executes."""
    logger.info(f"[{strategy_id}] Signal: {signal} | TV spot: {tv_spot}")
    accounts = get_active_accounts()
    if not accounts:
        logger.warning(f"[{strategy_id}] No active accounts")
        return

    logger.info(f"[{strategy_id}] Waiting {CANDLE_WAIT_SECONDS}s for next candle...")
    await asyncio.sleep(CANDLE_WAIT_SECONDS)

    now_ist = datetime.now(IST).time()
    from webhooks.utlrg import TRADING_END
    if now_ist > TRADING_END:
        logger.info(f"[{strategy_id}] Trading window closed after wait. Skipping.")
        return

    tasks = [execute_for_account(strategy_id, signal, acct, tv_spot) for acct in accounts]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for acct, result in zip(accounts, results):
        if isinstance(result, Exception):
            logger.error(f"[{strategy_id}][{acct['name']}] Failed: {result}", exc_info=result)


async def execute_for_account(strategy_id: str, signal: str, account: dict, tv_spot: float = None):
    """For one account: check limits, exit existing, enter new."""
    name = account["name"]
    today = date.today()

    if is_trading_halted(name, strategy_id, today):
        logger.info(f"[{strategy_id}][{name}] Halted by loss limit. Skipping.")
        return

    # get_open_trade returns a dict — no DetachedInstanceError possible
    open_trade = get_open_trade(name, strategy_id, today)
    if open_trade:
        logger.info(f"[{strategy_id}][{name}] Closing trade #{open_trade['id']} (REVERSE_SIGNAL)")
        success = await close_trade(open_trade, account, reason="REVERSE_SIGNAL")
        if not success:
            logger.error(f"[{strategy_id}][{name}] Exit failed — NOT entering new trade to avoid double position")
            return

    bias = get_day_bias(strategy_id)
    if bias == "no_trade":
        logger.info(f"[{strategy_id}][{name}] Bias=NO_TRADE — skipping entry")
        return
    elif bias == "bullish" and signal == "SELL":
        logger.info(f"[{strategy_id}][{name}] Bias=BULLISH — skipping SELL entry")
        return
    elif bias == "bearish" and signal == "BUY":
        logger.info(f"[{strategy_id}][{name}] Bias=BEARISH — skipping BUY entry")
        return
    await enter_trade(strategy_id, signal, account, tv_spot)


async def enter_trade(strategy_id: str, signal: str, account: dict, tv_spot: float = None):
    """Create trade record and execute entry order."""
    name = account["name"]
    today = date.today()

    # Spot price
    if tv_spot and tv_spot > 0:
        spot = tv_spot
        logger.info(f"[{strategy_id}][{name}] Spot from TV: Rs.{spot}")
    else:
        spot = await get_spot_price(account, strategy_id)
        if spot is None:
            logger.error(f"[{strategy_id}][{name}] Cannot get spot price. Aborting.")
            return
        logger.info(f"[{strategy_id}][{name}] Spot from Breeze: Rs.{spot}")

    signal_enum = Signal(signal)
    strike      = get_itm_strike(spot, signal_enum)
    option_type = get_option_type(signal_enum)
    expiry      = get_expiry_date(today)
    expiry_str  = get_expiry_string(today)   # e.g. "16-Jun-2026"
    lots        = account["quantity_lots"]
    lot_size    = get_lot_size(strategy_id)
    total_qty   = lots * lot_size

    logger.info(f"[{strategy_id}][{name}] Entering {signal}: {get_instrument(strategy_id)} {strike} {option_type.value} {expiry_str} | {lots}L={total_qty}u | {'PAPER' if account['paper_mode'] else 'LIVE'}")

    # Create trade record — capture ID before session closes
    with get_db() as db:
        t = Trade(
            trade_date=today,
            account_name=name,
            strategy_id=strategy_id,
            paper_mode=account["paper_mode"],
            signal=signal,
            signal_time=datetime.now(timezone.utc),
            instrument=get_instrument(strategy_id),
            strike=strike,
            option_type=option_type.value,
            expiry_date=expiry,
            quantity_lots=lots,
            lot_size=lot_size,
            total_quantity=total_qty,
            remaining_lots=lots,
            preclosure_done=False,
            entry_spot=spot,
        )
        db.add(t)
        db.flush()
        trade_id = t.id

    # Place order (async — outside session is fine, we only need trade_id)
    fill_price = await place_order(
        account=account, action="BUY", strike=strike,
        option_type=option_type.value, expiry_str=expiry_str,
        quantity=total_qty, strategy_id=strategy_id
    )

    # Save fill price in new session
    with get_db() as db:
        t = db.query(Trade).filter_by(id=trade_id).first()
        if t:
            t.entry_time  = datetime.now(timezone.utc)
            t.entry_price = fill_price if fill_price else 0.0

    if fill_price:
        logger.info(f"[{strategy_id}][{name}] Entry filled: Rs.{fill_price}")
    else:
        logger.error(f"[{strategy_id}][{name}] Entry order failed — no fill price")


async def close_trade(trade: dict, account: dict, reason: str) -> bool:
    """
    Close a position. trade is a DICT (from get_open_trade).
    Returns True if closed successfully, False on failure.
    """
    name        = account["name"]
    strategy_id = trade["strategy_id"]
    trade_id    = trade["id"]
    expiry_str  = trade["expiry_str"]   # already "16-Jun-2026" format

    fill_price = await place_order(
        account=account, action="SELL",
        strike=trade["strike"],
        option_type=trade["option_type"],
        expiry_str=expiry_str,
        quantity=(trade.get("remaining_lots") or trade["total_quantity"]) * trade["lot_size"],
        strategy_id=strategy_id
    )

    if fill_price is None:
        logger.error(f"[{strategy_id}][{name}] Exit failed for trade #{trade_id}")
        return False

    entry_price = trade["entry_price"] or 0.0
    remaining   = (trade.get("remaining_lots") or trade["quantity_lots"]) * trade["lot_size"]
    pnl         = (fill_price - entry_price) * remaining
    pnl_pct     = (pnl / (entry_price * remaining) * 100) if entry_price else 0.0

    with get_db() as db:
        t = db.query(Trade).filter_by(id=trade_id).first()
        if t:
            t.exit_time   = datetime.now(timezone.utc)
            t.exit_price  = fill_price
            t.exit_reason = reason
            t.pnl         = round(pnl, 2)
            t.pnl_pct     = round(pnl_pct, 2)

    update_daily_pnl(name, strategy_id, pnl)
    # Reset MTM to 0 — position is closed, no unrealised P&L
    with get_db() as db:
        r = db.query(DailyPnL).filter_by(
            account_name=name,
            strategy_id=strategy_id,
            pnl_date=date.today()
        ).first()
        if r:
            r.mtm_pnl = 0.0
            r.combined_pnl = r.realised_pnl
    logger.info(f"[{strategy_id}][{name}] Exit #{trade_id}: Rs.{fill_price} | P&L: Rs.{pnl:+.2f} | {reason}")
    return True


# ── Order execution ───────────────────────────────────────────────────────────

async def place_order(account: dict, action: str, strike: int, option_type: str,
                      expiry_str: str, quantity: int, strategy_id: str) -> Optional[float]:
    if account["paper_mode"]:
        return await paper_fill(account, strike, option_type, expiry_str, strategy_id)
    else:
        return await live_order(account, action, strike, option_type, expiry_str, quantity, strategy_id)


async def paper_fill(account: dict, strike: int, option_type: str,
                     expiry_str: str, strategy_id: str) -> Optional[float]:
    from core.breeze_client import get_ltp
    ltp = await get_ltp(account, get_instrument(strategy_id), strike, option_type, expiry_str)
    if ltp:
        logger.info(f"[{strategy_id}][{account['name']}] PAPER fill: Rs.{ltp}")
    else:
        logger.error(f"[{strategy_id}][{account['name']}] PAPER fill failed — LTP is None/0")
    return ltp


async def live_order(account: dict, action: str, strike: int, option_type: str,
                     expiry_str: str, quantity: int, strategy_id: str) -> Optional[float]:
    from core.breeze_client import place_limit_order, get_ltp
    buffer = account.get("limit_buffer", 5)
    name   = account["name"]
    for attempt in range(1, 3):
        ltp = await get_ltp(account, get_instrument(strategy_id), strike, option_type, expiry_str)
        if not ltp:
            logger.error(f"[{strategy_id}][{name}] Cannot get LTP for order")
            return None
        limit_price = round(ltp + buffer if action == "BUY" else ltp - buffer, 1)
        logger.info(f"[{strategy_id}][{name}] Attempt {attempt}: {action} {quantity}u {get_instrument(strategy_id)} {strike}{option_type} @ Rs.{limit_price}")
        order_id, fill_price = await place_limit_order(
            account=account, action=action, stock_code=get_instrument(strategy_id), strike=strike,
            option_type=option_type, expiry_str=expiry_str,
            quantity=quantity, limit_price=limit_price, timeout_seconds=10
        )
        if fill_price:
            logger.info(f"[{strategy_id}][{name}] Live fill: Rs.{fill_price}")
            return fill_price
        logger.warning(f"[{strategy_id}][{name}] Attempt {attempt} unfilled")
    logger.error(f"[{strategy_id}][{name}] Order failed after 2 attempts")
    return None


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def update_mtm(strategy_id: str):
    """Called every minute during market hours. Uses dict — no ORM issues."""
    from core.breeze_client import get_ltp
    accounts = get_active_accounts()
    today    = date.today()
    for account in accounts:
        trade = get_open_trade(account["name"], strategy_id, today)
        if not trade or not trade.get("entry_price"):
            continue
        ltp = await get_ltp(account, get_instrument(strategy_id), trade["strike"], trade["option_type"], trade["expiry_str"])
        if not ltp:
            continue
        remaining = trade.get("remaining_lots") or trade["total_quantity"] // trade["lot_size"]
        mtm = (ltp - trade["entry_price"]) * remaining * trade["lot_size"]
        
        # Profit pre-closure check
        if (trade["entry_price"] and ltp and 
            not trade.get("preclosure_done") and 
            account["preclosure_lots"] > 0 and
            remaining > account["preclosure_lots"]):
            profit_pct = ((ltp - trade["entry_price"]) / trade["entry_price"]) * 100
            if profit_pct >= account["profit_trigger"]:
                close_qty = account["preclosure_lots"] * trade["lot_size"]
                logger.info(f"[{strategy_id}][{account['name']}] Profit trigger {profit_pct:.1f}% — pre-closing {account['preclosure_lots']} lots")
                await place_order(account, "SELL", trade["strike"], trade["option_type"], trade["expiry_str"], close_qty, strategy_id)
                with get_db() as db:
                    t = db.query(Trade).filter_by(id=trade["id"], exit_time=None).first()
                    if t:
                        t.preclosure_done = True
                        t.remaining_lots = remaining - account["preclosure_lots"]
                logger.info(f"[{strategy_id}][{account['name']}] Pre-closure done. Remaining: {remaining - account['preclosure_lots']} lots")
        
        # Loss trigger check — close all remaining
        if (trade["entry_price"] and ltp and account["loss_trigger"] > 0):
            loss_pct = ((trade["entry_price"] - ltp) / trade["entry_price"]) * 100
            if loss_pct >= account["loss_trigger"]:
                logger.info(f"[{strategy_id}][{account['name']}] Loss trigger {loss_pct:.1f}% — closing all {remaining} lots")
                await close_trade(trade, account, reason="LOSS_TRIGGER")
                return
        spot = await get_spot_price(account, strategy_id)
        with get_db() as db:
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
                r.current_spot = round(spot, 2)
            loss_limit = account.get("daily_loss_limit", 0)
            if loss_limit and r.combined_pnl <= -abs(loss_limit) and not r.trading_halted:
                r.trading_halted = True
                r.halt_reason    = "DAILY_LOSS_LIMIT"
                logger.warning(f"[{account['name']}] LOSS LIMIT: Rs.{r.combined_pnl}")
                asyncio.create_task(close_trade(trade, account, reason="LOSS_LIMIT"))
        logger.info(f"[{account['name']}] MTM: Rs.{mtm:.2f} (LTP Rs.{ltp})")


async def exit_only_if_reversed(strategy_id: str, signal: str):
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


async def eod_squareoff(strategy_id: str):
    """Called at 15:20 IST. Squares off all open positions."""
    logger.info(f"[{strategy_id}] EOD square-off at 15:20 IST")
    accounts = get_active_accounts()
    today    = date.today()
    for account in accounts:
        trade = get_open_trade(account["name"], strategy_id, today)
        if trade:
            logger.info(f"[{strategy_id}][{account['name']}] EOD closing #{trade['id']}")
            await close_trade(trade, account, reason="EOD")
        else:
            logger.info(f"[{strategy_id}][{account['name']}] No open position at EOD")
    try:
        data = json.load(open("/opt/smb-algo-bn/config/strategies.json"))
        data["strategies"][0]["day_bias"] = "no_trade"
        json.dump(data, open("/opt/smb-algo-bn/config/strategies.json", "w"), indent=2)
        logger.info(f"[{strategy_id}] Day bias reset to range")
    except Exception as e:
        logger.warning(f"[{strategy_id}] Could not reset day bias: {e}")
