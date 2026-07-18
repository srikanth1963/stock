content = open('/opt/smb-algo-analytics/analytics_engine.py').read()

new_ep = """

@router.get("/api/analytics/poip")
async def poip_screener():
    try:
        cfg = get_analytics_config()
        mc = sqlite3.connect(MARKET_DB)
        tc = sqlite3.connect(TRADE_DB)
        try:
            as_of_date = mc.execute('SELECT MAX(date) FROM market_poip').fetchone()[0]
            pp_bull  = float(cfg.get('pp_bullish', 90))
            pp_bear  = float(cfg.get('pp_bearish', 10))
            oi_pct   = float(cfg.get('oi_pct', 90))
            hcoi_pct = float(cfg.get('hcoi_prox_pct', 0.75))
            hpoi_pct = float(cfg.get('hpoi_prox_pct', 0.75))
            c1_days  = int(cfg.get('cycle1_days', 20)); c1_llu = int(cfg.get('cycle1_llu', 14)); c1_ssc = int(cfg.get('cycle1_ssc', 14))
            c2_days  = int(cfg.get('cycle2_days', 10)); c2_llu = int(cfg.get('cycle2_llu', 8));  c2_ssc = int(cfg.get('cycle2_ssc', 8))

            poip_today = {r[0]: {'pp': r[1], 'oip': r[2]} for r in mc.execute(
                'SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip WHERE date=?', (as_of_date,)).fetchall()}

            oip_avg = {r[0]: r[1] for r in mc.execute(
                'SELECT nse_ticker, AVG(oi_percentile) FROM market_poip WHERE date IN (SELECT DISTINCT date FROM market_poip ORDER BY date DESC LIMIT 20) GROUP BY nse_ticker'
            ).fetchall()}

            stk_c1 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c1_days))
            stk_c2 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c2_days))
            bull_set = set(); bear_set = set()
            for t, s in stk_c1.items():
                if s['bull'] >= c1_llu: bull_set.add(t)
                if s['bear'] >= c1_ssc: bear_set.add(t)
            for t, s in stk_c2.items():
                if s['bull'] >= c2_llu: bull_set.add(t)
                if s['bear'] >= c2_ssc: bear_set.add(t)

            options_uni = set(r[0] for r in tc.execute('SELECT nse_ticker FROM stock_master WHERE is_active=1').fetchall())
            sec_map = {r[0]: r[1] for r in mc.execute('SELECT nse_ticker, sector FROM stock_sector').fetchall()}
            trap_date = mc.execute('SELECT MAX(date) FROM market_writers_trap').fetchone()[0]
            cwt_set = set(r[0] for r in mc.execute('SELECT nse_ticker FROM market_writers_trap WHERE signal_type=? AND date=?', ('CALL_WRITERS_TRAP', trap_date)).fetchall())
            pwt_set = set(r[0] for r in mc.execute('SELECT nse_ticker FROM market_writers_trap WHERE signal_type=? AND date=?', ('PUT_WRITERS_TRAP', trap_date)).fetchall())
            trig = {r[0]: {'futures': r[1], 'call_strike': r[2], 'call_diff': r[3], 'put_strike': r[4], 'put_diff': r[5]}
                   for r in mc.execute('SELECT nse_ticker, futures_price, call_strike, call_diff_pct, put_strike, put_diff_pct FROM market_oi_trigger WHERE date=?', (as_of_date,)).fetchall()}
            iv_d = {r[0]: r[1] for r in mc.execute('SELECT nse_ticker, ivp FROM market_iv WHERE date=?', (as_of_date,)).fetchall()}

            bullish = []; bearish = []
            for ticker, p in poip_today.items():
                is_bull = p['pp'] >= pp_bull and p['oip'] >= oi_pct
                is_bear = p['pp'] <= pp_bear and p['oip'] >= oi_pct
                if not is_bull and not is_bear: continue
                direction = 'Bullish' if is_bull else 'Bearish'
                in_cycle = ticker in (bull_set if is_bull else bear_set)
                if not in_cycle: continue
                s1 = stk_c1.get(ticker, {}); s2 = stk_c2.get(ticker, {})
                key = 'bull' if is_bull else 'bear'
                tr = trig.get(ticker, {})
                trap = ticker in (cwt_set if is_bull else pwt_set)
                cd = abs(tr.get('call_diff', 99) or 99)
                pd2 = abs(tr.get('put_diff', 99) or 99)
                bo_bd = cd <= hcoi_pct if is_bull else pd2 <= hpoi_pct
                pb = pd2 <= hpoi_pct if is_bull else cd <= hcoi_pct
                score = sum([trap, bo_bd, pb])
                entry = {
                    'ticker': ticker, 'sector': sec_map.get(ticker, 'Unknown'),
                    'instrument': 'Options' if ticker in options_uni else 'Spot',
                    'direction': direction, 'in_cycle': in_cycle,
                    'c1_score': f"{s1.get(key,0)}/{c1_days}", 'c2_score': f"{s2.get(key,0)}/{c2_days}",
                    'pp': p['pp'], 'oip': p['oip'], 'oip_avg_20': round(oip_avg.get(ticker, 0), 1),
                    'futures': tr.get('futures'), 'ivp': iv_d.get(ticker),
                    'call_strike': tr.get('call_strike'), 'call_diff': tr.get('call_diff'),
                    'put_strike': tr.get('put_strike'), 'put_diff': tr.get('put_diff'),
                    'trap': trap, 'score': score
                }
                (bullish if is_bull else bearish).append(entry)

            bullish.sort(key=lambda x: (-x['score'], x['ticker']))
            bearish.sort(key=lambda x: (-x['score'], x['ticker']))
            return {'status': 'ok', 'as_of_date': as_of_date, 'bullish': bullish, 'bearish': bearish,
                    'counts': {'bullish': len(bullish), 'bearish': len(bearish)}}
        finally:
            mc.close(); tc.close()
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
