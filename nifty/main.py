"""
SMB Algo Platform — Main Application
FastAPI app: webhook receiver, REST API, scheduler.
"""

import logging
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone=IST)


async def morning_entry_job():
    """
    9:26 AM IST — waits 30 seconds for TV webhook to arrive and update
    stored signal, then enters trade based on latest stored signal.
    This ensures overnight signal flips are captured before entry.
    """
    from datetime import date
    from core.signal_state import get_last_signal
    from core.order_router import get_open_trade, enter_trade
    from core.accounts import get_active_accounts

    logger.info("[morning_entry] Waiting 30s for TV webhook...")
    await asyncio.sleep(30)

    today = date.today()
    sig = get_last_signal("utlrg")
    if not sig:
        logger.info("[morning_entry] No stored signal. Skipping.")
        return
    signal = sig["signal"]
    logger.info(f"[morning_entry] Stored signal after wait: {signal}")
    from core.order_router import get_day_bias
    bias = get_day_bias("utlrg")
    if bias == "no_trade":
        logger.info(f"[morning_entry] Bias=NO_TRADE — skipping morning entry")
        return
    for account in get_active_accounts():
        if not get_open_trade(account["name"], "utlrg", today):
            if bias == "bullish" and signal == "SELL":
                logger.info(f"[morning_entry] Bias=BULLISH — skipping SELL entry for {account['name']}")
                continue
            if bias == "bearish" and signal == "BUY":
                logger.info(f"[morning_entry] Bias=BEARISH — skipping BUY entry for {account['name']}")
                continue
            logger.info(f"[morning_entry] Entering {signal} for {account['name']}")
            await enter_trade("utlrg", signal, account)
        else:
            logger.info(f"[morning_entry] {account['name']} already has position. Skipping.")


async def eod_squareoff_job():
    """3:20 PM IST — square off all positions."""
    from core.order_router import eod_squareoff
    await eod_squareoff("utlrg")


async def mtm_update_job():
    """Every minute — update MTM P&L."""
    from core.order_router import update_mtm
    await update_mtm("utlrg")


def setup_scheduler():
    """Register all scheduled jobs."""
    from strategies.utlrg.expiry import load_nse_holidays

    scheduler.add_job(
        func=morning_entry_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=9, minute=26,
        id="morning_entry_utlrg",
        replace_existing=True
    )

    scheduler.add_job(
        func=eod_squareoff_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=15, minute=20,
        id="eod_squareoff_utlrg",
        replace_existing=True
    )

    scheduler.add_job(
        func=mtm_update_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-14",
        minute="*/1",
        id="mtm_update_utlrg",
        replace_existing=True
    )

    scheduler.add_job(
        func=load_nse_holidays.cache_clear,
        trigger="cron",
        hour=0, minute=0,
        id="reload_holidays",
        replace_existing=True
    )

    logger.info("Scheduler jobs registered: morning entry, EOD squareoff, MTM update, holiday reload")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("SMB Algo Platform starting...")
    from core.database import init_db
    init_db()
    setup_scheduler()
    scheduler.start()
    # Pre-warm Breeze session so first TV webhook doesn't timeout
    try:
        from core.accounts import get_active_accounts
        from core.breeze_client import get_breeze
        for account in get_active_accounts():
            breeze = get_breeze(account)
            if breeze:
                logger.info(f"Breeze pre-warmed for {account['name']}")
            else:
                logger.warning(f"Breeze pre-warm failed for {account['name']} — no session token?")
    except Exception as e:
        logger.warning(f"Breeze pre-warm error: {e}")
    logger.info("SMB Algo Platform ready ✓")
    yield
    scheduler.shutdown()
    logger.info("SMB Algo Platform stopped")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SMB Algo Platform",
    description="Multi-strategy algorithmic trading platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent / "frontend"

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")

# ── Routers ───────────────────────────────────────────────────────────────────
from webhooks.utlrg import router as utlrg_webhook
from auth.breeze_auth import router as auth_router
from api.routes import router as api_router

app.include_router(utlrg_webhook)
app.include_router(auth_router)
app.include_router(api_router)


@app.get("/health")
async def health():
    from datetime import datetime
    return {
        "status": "ok",
        "platform": "SMB Algo",
        "version": "1.0.0",
        "time_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
