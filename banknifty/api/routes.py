"""
SMB Algo — REST API Routes
Serves data to the React frontend dashboard.
"""

import logging
import json
import re
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request
from zoneinfo import ZoneInfo

from core.database import get_db, Trade, DailyPnL
from core.accounts import get_all_accounts
from core.signal_state import get_last_signal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
IST = ZoneInfo("Asia/Kolkata")


def dt_iso(dt):
    """Convert datetime to ISO string with Z suffix (UTC indicator)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


@router.get("/dashboard")
async def dashboard():
    """Master dashboard data — all accounts, all positions, today P&L."""
    today = date.today()
    accounts = get_all_accounts()
    result = []

    with get_db() as db:
        for account in accounts:
            name = account["name"]

            open_trade = db.query(Trade).filter_by(
                account_name=name,
                strategy_id="utlrg",
                trade_date=today,
                exit_time=None
            ).first()

            pnl_record = db.query(DailyPnL).filter_by(
                account_name=name,
                strategy_id="utlrg",
                pnl_date=today
            ).first()

            position = None
            if open_trade:
                position = {
                    "id": open_trade.id,
                    "signal": open_trade.signal,
                    "strike": open_trade.strike,
                    "option_type": open_trade.option_type,
                    "expiry": open_trade.expiry_date.isoformat(),
                    "lots": open_trade.quantity_lots,
                    "entry_price": open_trade.entry_price,
                    "entry_time": dt_iso(open_trade.entry_time),
                    "entry_spot": open_trade.entry_spot,
                    "current_ltp": open_trade.current_ltp,
                    "current_spot": pnl_record.current_spot if pnl_record else None,
                    "total_quantity": open_trade.total_quantity,
                }

            result.append({
                "account": name,
                "paper_mode": account["paper_mode"],
                "active": account["active"],
                "daily_loss_limit": account["daily_loss_limit"],
                "quantity_lots": account["quantity_lots"],
                "trading_halted": pnl_record.trading_halted if pnl_record else False,
                "realised_pnl": pnl_record.realised_pnl if pnl_record else 0,
                "mtm_pnl": pnl_record.mtm_pnl if pnl_record else 0,
                "combined_pnl": pnl_record.combined_pnl if pnl_record else 0,
                "trade_count": pnl_record.trade_count if pnl_record else 0,
                "open_position": position,
            })

    last_signal = get_last_signal("utlrg")
    if last_signal and last_signal.get("signal_time"):
        last_signal["signal_time"] = dt_iso(last_signal["signal_time"])

    from strategies.utlrg.expiry import get_holiday_status
    holiday_status = get_holiday_status()

    system = {
        "webhook_active": True,
        "breeze_connected": sum(1 for a in accounts if not a["paper_mode"]),
        "scheduler_running": True,
        "day_bias": json.load(open("/opt/smb-algo-bn/config/strategies.json"))["strategies"][0].get("day_bias", "range"),
    }

    return {
        "date": today.isoformat(),
        "time": datetime.now(IST).isoformat(),
        "last_signal": last_signal,
        "holiday_status": holiday_status,
        "system": system,
        "accounts": result
    }


@router.get("/trades")
async def get_trades(account: str = None, days: int = 7):
    """Trade history with optional account filter."""
    since = date.today() - timedelta(days=days)

    with get_db() as db:
        query = db.query(Trade).filter(Trade.trade_date >= since)
        if account:
            query = query.filter_by(account_name=account)
        trades = query.order_by(Trade.trade_date.desc(), Trade.entry_time.desc()).all()

        # Build response INSIDE the session to avoid DetachedInstanceError
        trade_list = [
            {
                "id": t.id,
                "date": t.trade_date.isoformat(),
                "account": t.account_name,
                "paper_mode": t.paper_mode,
                "signal": t.signal,
                "instrument": f"{t.instrument} {t.strike} {t.option_type}",
                "expiry": t.expiry_date.isoformat(),
                "lots": t.quantity_lots,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "entry_time": dt_iso(t.entry_time),
                "exit_time": dt_iso(t.exit_time),
            }
            for t in trades
        ]

    return {"trades": trade_list}


@router.post("/kill/{account_name}")
async def kill_switch(account_name: str):
    """Manual kill switch."""
    from core.accounts import get_account
    from core.order_router import get_open_trade, close_trade

    account = get_account(account_name)
    if not account:
        return {"status": "error", "message": f"Account not found: {account_name}"}

    today = date.today()
    open_trade = get_open_trade(account_name, "utlrg", today)

    if open_trade:
        await close_trade(open_trade, account, reason="KILL")
        msg = f"Position closed via kill switch for {account_name}"
    else:
        msg = f"No open position for {account_name}"

    with get_db() as db:
        record = db.query(DailyPnL).filter_by(
            account_name=account_name,
            strategy_id="utlrg",
            pnl_date=today
        ).first()
        if not record:
            record = DailyPnL(account_name=account_name, strategy_id="utlrg", pnl_date=today)
            db.add(record)
        record.trading_halted = True
        record.halt_reason = "KILL_SWITCH"

    logger.warning(f"Kill switch activated for {account_name}")
    return {"status": "ok", "message": msg}


@router.post("/kill-all")
async def kill_all():
    """Master kill switch."""
    accounts = get_all_accounts()
    results = []
    for account in accounts:
        if account["active"]:
            result = await kill_switch(account["name"])
            results.append({"account": account["name"], **result})
    return {"status": "ok", "results": results}


@router.post("/settings/lot-size")
async def update_lot_size(request: Request):
    """Update Nifty lot size in strategies.json config."""
    data = await request.json()
    new_lot_size = int(data.get("lot_size", 65))
    if new_lot_size < 1 or new_lot_size > 1000:
        return {"status": "error", "message": "Invalid lot size"}
    config_path = "/opt/smb-algo-bn/config/strategies.json"
    strategies = json.load(open(config_path))
    old_size = strategies["strategies"][0]["lot_size"]
    strategies["strategies"][0]["lot_size"] = new_lot_size
    json.dump(strategies, open(config_path, "w"), indent=2)
    logger.info(f"Lot size updated: {old_size} to {new_lot_size}")
    return {"status": "ok", "lot_size": new_lot_size, "message": f"Lot size updated to {new_lot_size}"}


@router.post("/settings/trading-mode")
async def update_trading_mode(request: Request):
    """Switch account between paper and live trading mode."""
    data = await request.json()
    account_name = data.get("account_name", "Primary")
    paper_mode = data.get("paper_mode", True)
    accounts = get_all_accounts()
    account_num = next((i for i, a in enumerate(accounts, 1) if a["name"] == account_name), None)
    if not account_num:
        return {"status": "error", "message": "Account not found"}
    key = f"ACCOUNT{account_num}_PAPER_MODE"
    env_path = "/opt/smb-algo-bn/.env"
    content = open(env_path).read()
    value = "true" if paper_mode else "false"
    if key in content:
        content = re.sub(f"{key}=.*", f"{key}={value}", content)
    else:
        content += f"\n{key}={value}\n"
    open(env_path, "w").write(content)
    mode = "Paper Trading" if paper_mode else "LIVE TRADING"
    logger.warning(f"Trading mode changed to {mode} for {account_name}")
    return {"status": "ok", "paper_mode": paper_mode, "message": f"Switched to {mode}"}


@router.post("/settings/day-bias")
async def update_day_bias(request: Request):
    """Update day bias in strategies.json."""
    data = await request.json()
    bias = data.get("day_bias", "range").lower()
    if bias not in ("range", "bullish", "bearish", "no_trade"):
        return {"status": "error", "message": f"Invalid bias: {bias}"}
    import json as j
    cfg_path = "/opt/smb-algo-bn/config/strategies.json"
    cfg = j.load(open(cfg_path))
    cfg["strategies"][0]["day_bias"] = bias
    j.dump(cfg, open(cfg_path, "w"), indent=2)
    logger.info(f"Day bias updated to {bias}")
    return {"status": "ok", "day_bias": bias}


@router.post("/settings/account")
async def update_account_settings(request: Request):
    """Update quantity lots, daily loss limit and limit buffer in .env"""
    data = await request.json()
    account_name = data.get("account_name", "Primary")
    accounts = get_all_accounts()
    account_num = next((i for i, a in enumerate(accounts, 1) if a["name"] == account_name), None)
    if not account_num:
        return {"status": "error", "message": "Account not found"}
    env_path = "/opt/smb-algo-bn/.env"
    content = open(env_path).read()
    prefix = f"ACCOUNT{account_num}_"
    updates = {}
    if "quantity_lots" in data:
        updates[f"{prefix}QUANTITY_LOTS"] = str(int(data["quantity_lots"]))
    if "daily_loss_limit" in data:
        updates[f"{prefix}DAILY_LOSS_LIMIT"] = str(float(data["daily_loss_limit"]))
    if "limit_buffer" in data:
        updates[f"{prefix}LIMIT_BUFFER"] = str(float(data["limit_buffer"]))
    import re
    for key, value in updates.items():
        if key in content:
            content = re.sub(f"{key}=.*", f"{key}={value}", content)
        else:
            content += f"\n{key}={value}\n"
    open(env_path, "w").write(content)
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    logger.info(f"Account settings updated: {updates}")
    return {"status": "ok", "updates": updates}


@router.post("/settings/preclosure")
async def update_preclosure_settings(request: Request):
    """Update pre-closure lots, profit trigger and loss trigger in .env"""
    data = await request.json()
    account_name = data.get("account_name", "Primary")
    accounts = get_all_accounts()
    account_num = next((i for i, a in enumerate(accounts, 1) if a["name"] == account_name), None)
    if not account_num:
        return {"status": "error", "message": "Account not found"}
    env_path = "/opt/smb-algo-bn/.env"
    content = open(env_path).read()
    prefix = f"ACCOUNT{account_num}_"
    updates = {}
    if "preclosure_lots" in data:
        updates[f"{prefix}PRECLOSURE_LOTS"] = str(int(data["preclosure_lots"]))
    if "profit_trigger" in data:
        updates[f"{prefix}PROFIT_TRIGGER"] = str(float(data["profit_trigger"]))
    if "loss_trigger" in data:
        updates[f"{prefix}LOSS_TRIGGER"] = str(float(data["loss_trigger"]))
    import re
    for key, value in updates.items():
        if key in content:
            content = re.sub(f"{key}=.*", f"{key}={value}", content)
        else:
            content += f"\n{key}={value}\n"
    open(env_path, "w").write(content)
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    logger.info(f"Preclosure settings updated: {updates}")
    return {"status": "ok", "updates": updates}
