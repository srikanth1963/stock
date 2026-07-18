"""
Patch script for EOD trading rules:
1. _process_signal: after 3PM, reversal exits immediately, no new entry
2. eod_squareoff_job: triggers at 3:18 PM instead of 3:20 PM
3. _execute_exit: retry every 10s until 3:22 PM, then force close
"""
import subprocess

lines = open('/opt/smb-algo-stocks/main.py').readlines()

# ── Fix 1: eod_squareoff_job trigger time 3:20 → 3:18 ────────────────────────
content = open('/opt/smb-algo-stocks/main.py').read()

old1 = 'scheduler.add_job(eod_squareoff_job, CronTrigger(hour=15, minute=20, second=0, timezone="Asia/Kolkata"))'
new1 = 'scheduler.add_job(eod_squareoff_job, CronTrigger(hour=15, minute=18, second=0, timezone="Asia/Kolkata"))'
if old1 in content:
    content = content.replace(old1, new1)
    print('Fix 1 applied: EOD squareoff trigger changed to 3:18 PM')
else:
    print('Fix 1 NOT FOUND')

# ── Fix 2: _process_signal post-3PM reversal → exit immediately ───────────────
old2 = '''        else:
            if not is_entry_allowed():
                return {"status": "stored", "reason": "post 3PM signal reversal stored"}
            logger.info(f"[{acc.account_name}] Signal reversal {ticker}")
            await enqueue(acc_id, _execute_exit, open_trade.id, "SIGNAL_REVERSAL", acc_id)
            await enqueue(acc_id, _execute_entry, acc_id, ticker, direction)
            return {"status": "queued", "reason": "signal reversal"}'''
new2 = '''        else:
            if not is_entry_allowed():
                # After 3PM: exit immediately, store signal, no new entry
                logger.info(f"[{acc.account_name}] Post-3PM reversal {ticker}: exiting, no new entry")
                await enqueue(acc_id, _execute_exit, open_trade.id, "SIGNAL_REVERSAL_POST3PM", acc_id)
                return {"status": "queued", "reason": "post 3PM reversal exit queued"}
            logger.info(f"[{acc.account_name}] Signal reversal {ticker}")
            await enqueue(acc_id, _execute_exit, open_trade.id, "SIGNAL_REVERSAL", acc_id)
            await enqueue(acc_id, _execute_entry, acc_id, ticker, direction)
            return {"status": "queued", "reason": "signal reversal"}'''
if old2 in content:
    content = content.replace(old2, new2)
    print('Fix 2 applied: post-3PM reversal exits immediately, no new entry')
else:
    print('Fix 2 NOT FOUND')

open('/opt/smb-algo-stocks/main.py', 'w').write(content)

# ── Fix 3: _execute_exit retry logic ─────────────────────────────────────────
# Find the paper exit block and replace with full retry logic
content = open('/opt/smb-algo-stocks/main.py').read()

old3 = '''        if paper:
            exit_price = trade.current_ltp or trade.entry_price
            logger.info(f"PAPER exit: {trade.nse_ticker} @ {exit_price}")
        else:
            breeze = get_breeze()
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
                    if acc and acc.order_price_type == "aggressive":
                        exit_price = float(rows[0].get("best_bid_price", exit_price))
                    else:
                        exit_price = float(rows[0].get("ltp", exit_price))

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
            if resp2.get("Status") != 200:
                logger.error(f"Exit order failed for {trade.nse_ticker}: {resp2.get('Error')}")
                return'''

new3 = '''        import asyncio as _asyncio
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
                logger.warning(f"Force closing {trade.nse_ticker} in DB at {exit_price}")'''

if old3 in content:
    content = content.replace(old3, new3)
    print('Fix 3 applied: retry logic with 10s intervals and post-3:22 force close')
else:
    print('Fix 3 NOT FOUND')

open('/opt/smb-algo-stocks/main.py', 'w').write(content)

# Verify syntax
result = subprocess.run(['python3', '-m', 'py_compile', '/opt/smb-algo-stocks/main.py'], capture_output=True)
if result.returncode == 0:
    print('Syntax OK')
else:
    print('Syntax ERROR:', result.stderr.decode())
