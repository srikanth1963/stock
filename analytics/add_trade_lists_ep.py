content = open('/opt/smb-algo-analytics/analytics_engine.py').read()

new_ep = """

@router.get("/api/analytics/trade_lists/combined")
async def get_combined_trade_list(as_of_date: Optional[str] = None):
    \"\"\"Combine OI Buildup + POIP + Writers Trap into a single bullish/bearish trade list.\"\"\"
    try:
        cfg = get_analytics_config()
        mc = sqlite3.connect(MARKET_DB)
        tc = sqlite3.connect(TRADE_DB)
        try:
            if not as_of_date:
                as_of_date = mc.execute("SELECT MAX(date) FROM market_oi_buildup").fetchone()[0]

            # Run all three screeners
            from analytics_engine import run_oi_buildup
            oi_result   = run_oi_buildup(cfg, as_of_date)

            # POIP stocks
            pp_bull  = float(cfg.get('pp_bullish', 90))
            pp_bear  = float(cfg.get('pp_bearish', 10))
            oi_pct   = float(cfg.get('oi_pct', 90))
            c1_days  = int(cfg.get('cycle1_days', 20)); c1_llu = int(cfg.get('cycle1_llu', 14)); c1_ssc = int(cfg.get('cycle1_ssc', 14))
            c2_days  = int(cfg.get('cycle2_days', 10)); c2_llu = int(cfg.get('cycle2_llu', 8));  c2_ssc = int(cfg.get('cycle2_ssc', 8))

            poip_today = {r[0]: {'pp': r[1], 'oip': r[2]} for r in mc.execute(
                'SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip WHERE date=?', (as_of_date,)).fetchall()}
            stk_c1 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c1_days))
            stk_c2 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c2_days))
            bull_set = set(); bear_set = set()
            for t,s in stk_c1.items():
                if s['bull'] >= c1_llu: bull_set.add(t)
                if s['bear'] >= c1_ssc: bear_set.add(t)
            for t,s in stk_c2.items():
                if s['bull'] >= c2_llu: bull_set.add(t)
                if s['bear'] >= c2_ssc: bear_set.add(t)

            poip_bull = {t for t,p in poip_today.items() if p['pp'] >= pp_bull and p['oip'] >= oi_pct and t in bull_set}
            poip_bear = {t for t,p in poip_today.items() if p['pp'] <= pp_bear and p['oip'] >= oi_pct and t in bear_set}

            # Writers Trap stocks
            trap_date = mc.execute('SELECT MAX(signal_date) FROM market_writers_trap').fetchone()[0]
            cwt_set = set(r[0] for r in mc.execute('SELECT nse_ticker FROM market_writers_trap WHERE signal_type=? AND signal_date=?', ('CALL_WRITERS_TRAP', trap_date)).fetchall())
            pwt_set = set(r[0] for r in mc.execute('SELECT nse_ticker FROM market_writers_trap WHERE signal_type=? AND signal_date=?', ('PUT_WRITERS_TRAP', trap_date)).fetchall())
            cwt_bull = cwt_set & bull_set
            pwt_bear = pwt_set & bear_set

            # OI Buildup stocks
            oi_bull = {s['ticker'] for s in oi_result['bullish']}
            oi_bear = {s['ticker'] for s in oi_result['bearish']}

            # Combine and deduplicate
            all_bull = oi_bull | poip_bull | cwt_bull
            all_bear = oi_bear | poip_bear | pwt_bear

            # Get accounts
            accounts = tc.execute('SELECT id, account_name, dp_name, status FROM account_config ORDER BY id').fetchall()

            # Get existing approved list for today
            approved = {r[0]: r[1] for r in tc.execute(
                "SELECT nse_ticker, account_ids FROM trade_lists WHERE date=? AND strategy='UTLRG'", (as_of_date,)).fetchall()}

            def build_entry(ticker, direction):
                sources = []
                if ticker in (oi_bull if direction=='Bullish' else oi_bear): sources.append('OI')
                if ticker in (poip_bull if direction=='Bullish' else poip_bear): sources.append('POIP')
                if ticker in (cwt_bull if direction=='Bullish' else pwt_bear): sources.append('Trap')
                return {
                    'ticker': ticker,
                    'direction': direction,
                    'sources': '+'.join(sources),
                    'source_count': len(sources),
                    'approved': ticker in approved,
                    'account_ids': approved.get(ticker, '')
                }

            bullish = sorted([build_entry(t, 'Bullish') for t in all_bull], key=lambda x: (-x['source_count'], x['ticker']))
            bearish = sorted([build_entry(t, 'Bearish') for t in all_bear], key=lambda x: (-x['source_count'], x['ticker']))

            return {
                'status': 'ok',
                'as_of_date': as_of_date,
                'accounts': [{'id': a[0], 'name': a[2] or a[1], 'status': a[3]} for a in accounts],
                'bullish': bullish,
                'bearish': bearish,
                'counts': {'bullish': len(bullish), 'bearish': len(bearish)}
            }
        finally:
            mc.close(); tc.close()
    except Exception as ex:
        import traceback
        return {'status': 'error', 'error': str(ex), 'trace': traceback.format_exc()}


@router.post("/api/analytics/trade_lists/approve")
async def approve_trade_list(request):
    \"\"\"Save approved trade list and update account_stocks.\"\"\"
    try:
        body = await request.json()
        date = body.get('date')
        stocks = body.get('stocks', [])  # [{ticker, direction, account_ids: [1,2,3]}]

        tc = sqlite3.connect(TRADE_DB)
        try:
            from datetime import datetime as _dt
            now = _dt.utcnow().isoformat()

            # Save to trade_lists
            tc.execute("DELETE FROM trade_lists WHERE date=? AND strategy='UTLRG'", (date,))
            for s in stocks:
                acct_ids = ','.join(str(a) for a in s.get('account_ids', []))
                tc.execute(
                    "INSERT OR REPLACE INTO trade_lists (date, strategy, nse_ticker, direction, sources, account_ids, approved, approved_at) VALUES (?,?,?,?,?,?,1,?)",
                    (date, 'UTLRG', s['ticker'], s['direction'], s.get('sources',''), acct_ids, now)
                )

            # Update account_stocks per account
            # Group stocks by account
            from collections import defaultdict
            acct_stocks = defaultdict(list)
            for s in stocks:
                for aid in s.get('account_ids', []):
                    acct_stocks[int(aid)].append(s['ticker'])

            for acct_id, tickers in acct_stocks.items():
                # Replace account_stocks for this account
                tc.execute('DELETE FROM account_stocks WHERE account_id=?', (acct_id,))
                for ticker in tickers:
                    tc.execute('INSERT OR IGNORE INTO account_stocks (account_id, nse_ticker) VALUES (?,?)', (acct_id, ticker))

            tc.commit()
            return {'status': 'ok', 'approved': len(stocks)}
        finally:
            tc.close()
    except Exception as ex:
        import traceback
        return {'status': 'error', 'error': str(ex), 'trace': traceback.format_exc()}
"""

open('/opt/smb-algo-analytics/analytics_engine.py', 'w').write(content + new_ep)

import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/opt/smb-algo-analytics/analytics_engine.py'], capture_output=True)
if result.returncode == 0:
    print('Syntax OK')
else:
    print('ERROR:', result.stderr.decode())
