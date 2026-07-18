# Fix get_ltp in breeze_client.py — add retry on empty response

content = open('/opt/smb-algo/core/breeze_client.py').read()

old = '''async def get_ltp(account: dict, symbol: str, strike: int,
                  option_type: str, expiry_str: str) -> Optional[float]:
    """Fetch last traded price for a specific options contract."""
    breeze = get_breeze(account)
    if not breeze:
        # Offline paper trading fallback
        mock = 150.0
        logger.info(f"[{account['name']}] Mock LTP ₹{mock} for {symbol} {strike} {option_type}")
        return mock
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: breeze.get_quotes(
            stock_code=symbol,
            exchange_code="NFO",
            expiry_date=expiry_str,
            product_type="options",
            right="call" if option_type == "CE" else "put",
            strike_price=str(strike)
        ))
        nse_rows = [r for r in result["Success"] if r.get("exchange_code") in ("NSE", "NFO")]
        ltp = float(nse_rows[0]["ltp"]) if nse_rows else 0.0
        logger.debug(f"[{account['name']}] LTP {symbol} {strike} {option_type}: ₹{ltp}")
        return ltp
    except Exception as e:
        logger.error(f"[{account['name']}] get_ltp failed: {e}")
        return None'''

new = '''async def get_ltp(account: dict, symbol: str, strike: int,
                  option_type: str, expiry_str: str) -> Optional[float]:
    """Fetch last traded price. Retries once on empty/failed response."""
    breeze = get_breeze(account)
    if not breeze:
        mock = 150.0
        logger.info(f"[{account['name']}] Mock LTP Rs.{mock} for {symbol} {strike} {option_type}")
        return mock
    for attempt in range(1, 3):
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: breeze.get_quotes(
                stock_code=symbol,
                exchange_code="NFO",
                expiry_date=expiry_str,
                product_type="options",
                right="call" if option_type == "CE" else "put",
                strike_price=str(strike)
            ))
            rows = [r for r in result["Success"] if r.get("exchange_code") in ("NSE", "NFO")]
            ltp = float(rows[0]["ltp"]) if rows else 0.0
            if ltp > 0:
                logger.debug(f"[{account['name']}] LTP {symbol} {strike} {option_type}: Rs.{ltp}")
                return ltp
            logger.warning(f"[{account['name']}] LTP=0 for {strike}{option_type} attempt {attempt}")
        except Exception as e:
            logger.error(f"[{account['name']}] get_ltp attempt {attempt} failed: {e}")
        if attempt < 2:
            await asyncio.sleep(1)
    logger.error(f"[{account['name']}] get_ltp failed after 2 attempts for {strike}{option_type}")
    return None'''

if old in content:
    content = content.replace(old, new)
    open('/opt/smb-algo/core/breeze_client.py', 'w').write(content)
    print("Fixed!")
else:
    print("ERROR: Pattern not found")
    import sys; sys.exit(1)
