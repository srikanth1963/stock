"""
Adds Day Bias to SMB Algo Stocks:
1. day_bias added to app_state (default: 'range')
2. POST /stocks/api/day_bias endpoint
3. Bias check in _process_signal
4. EOD reset to 'range' in eod_squareoff_job
"""
import subprocess

content = open('/opt/smb-algo-stocks/main.py').read()

# Fix 1: Add day_bias to app_state
old1 = '''app_state = {
    "trading_enabled": True,
    "account_status": {},
}'''
new1 = '''app_state = {
    "trading_enabled": True,
    "account_status": {},
    "day_bias": "range",
}'''
if old1 in content:
    content = content.replace(old1, new1)
    print('Fix 1 applied: day_bias added to app_state')
else:
    print('Fix 1 NOT FOUND')

# Fix 2: Add bias check in _process_signal before queuing entry
old2 = '''    if not is_entry_allowed():
        return {"status": "stored", "reason": "post 3PM no entry"}

    open_count = db.query(Trade).filter(
        Trade.account_id == acc_id, Trade.status == "OPEN"
    ).count()
    if open_count >= 25:
        return {"status": "queued_pending", "reason": "at concurrent trade limit"}

    await enqueue(acc_id, _execute_entry, acc_id, ticker, direction)
    return {"status": "queued", "reason": "fresh entry"}'''
new2 = '''    if not is_entry_allowed():
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
    return {"status": "queued", "reason": "fresh entry"}'''
if old2 in content:
    content = content.replace(old2, new2)
    print('Fix 2 applied: bias check in _process_signal')
else:
    print('Fix 2 NOT FOUND')

# Fix 3: Reset day_bias to range in EOD squareoff
old3 = '''        logger.info("EOD squareoff job triggered at 3:20 PM")'''
new3 = '''        logger.info("EOD squareoff job triggered at 3:18 PM")
        app_state["day_bias"] = "range"
        logger.info("Day bias reset to RANGE for next session")'''
if old3 in content:
    content = content.replace(old3, new3)
    print('Fix 3 applied: day_bias reset at EOD')
else:
    print('Fix 3 NOT FOUND')

# Fix 4: Add day_bias API endpoint
old4 = '''@app.post("/stocks/api/refresh_session")'''
new4 = '''@app.post("/stocks/api/day_bias")
async def set_day_bias(request: Request):
    """Set day bias: range / bullish / bearish / no_trade"""
    body = await request.json()
    bias = body.get("bias", "range").lower()
    if bias not in ("range", "bullish", "bearish", "no_trade"):
        raise HTTPException(status_code=400, detail="Invalid bias value")
    app_state["day_bias"] = bias
    logger.info(f"Day bias set to: {bias.upper()}")
    return {"status": "ok", "day_bias": bias}


@app.get("/stocks/api/day_bias")
async def get_day_bias():
    return {"day_bias": app_state.get("day_bias", "range")}


@app.post("/stocks/api/refresh_session")'''
if old4 in content:
    content = content.replace(old4, new4)
    print('Fix 4 applied: day_bias API endpoints added')
else:
    print('Fix 4 NOT FOUND')

open('/opt/smb-algo-stocks/main.py', 'w').write(content)

# Verify syntax
result = subprocess.run(['python3', '-m', 'py_compile', '/opt/smb-algo-stocks/main.py'], capture_output=True)
if result.returncode == 0:
    print('Syntax OK')
else:
    print('Syntax ERROR:', result.stderr.decode())
