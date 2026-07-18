lines = open('/opt/smb-algo-stocks/main.py').readlines()

# Verify we have the right lines before changing anything
assert '# Place order' in lines[352], f"Line 353 unexpected: {lines[352]}"
assert 'order_id = resp.get' in lines[375], f"Line 376 unexpected: {lines[375]}"

new_block = []
new_block.append('        # Place order (skip if paper trading)\n')
new_block.append('        if acc.paper_trading:\n')
new_block.append('            logger.info(f"[{acc.account_name}] PAPER trade: {ticker} {direction} @ {order_price}")\n')
new_block.append('            order_id = "PAPER"\n')
new_block.append('        else:\n')
new_block.append('            resp = breeze.place_order(\n')
new_block.append('                stock_code=stock.breeze_code,\n')
new_block.append('                exchange_code="NFO",\n')
new_block.append('                product="options",\n')
new_block.append('                action="buy",\n')
new_block.append('                order_type="limit",\n')
new_block.append('                stoploss="0",\n')
new_block.append('                quantity=str(quantity),\n')
new_block.append('                price=str(order_price),\n')
new_block.append('                validity="day",\n')
new_block.append('                validity_date=datetime.now().strftime("%Y-%m-%dT06:00:00.000Z"),\n')
new_block.append('                disclosed_quantity="0",\n')
new_block.append('                expiry_date=expiry_breeze,\n')
new_block.append('                right=right,\n')
new_block.append('                strike_price=str(result["selected_strike"]),\n')
new_block.append('                user_remark="SMB-" + ticker + "-" + direction\n')
new_block.append('            )\n')
new_block.append('            if resp.get("Status") != 200:\n')
new_block.append('                logger.error(f"Order placement failed for {ticker}: " + str(resp.get("Error")))\n')
new_block.append('                return\n')
new_block.append('            order_id = resp.get("Success", {}).get("order_id", "")\n')

lines[352:376] = new_block
open('/opt/smb-algo-stocks/main.py', 'w').writelines(lines)
print('Done successfully')
