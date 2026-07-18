"""
analytics_engine.py — SMB Algo Analytics Engine
OI Buildup Screener with A+B+C+D+E sub-lists and enriched corroborative columns
"""
import sqlite3
import logging
from typing import Optional
from fastapi import APIRouter

logger = logging.getLogger(__name__)

MARKET_DB = "/opt/smb-algo-stocks/market_data.db"
TRADE_DB  = "/opt/smb-algo-stocks/trade.db"

router = APIRouter()


def get_analytics_config() -> dict:
    mc = sqlite3.connect(MARKET_DB)
    try:
        return {r[0]: r[1] for r in mc.execute("SELECT key, value FROM analytics_config").fetchall()}
    finally:
        mc.close()


def get_trading_dates(mc, table, as_of_date, lookback):
    """Get last N actual trading dates."""
    rows = mc.execute(
        f"SELECT DISTINCT date FROM {table} WHERE date <= ? ORDER BY date DESC LIMIT ?",
        (as_of_date, int(lookback))
    ).fetchall()
    return [r[0] for r in rows]


def get_llu_scores(mc, dates):
    """Get L:LU and S:SC counts per stock for given trading dates."""
    if not dates:
        return {}
    ph = ','.join('?' * len(dates))
    rows = mc.execute(f"""
        SELECT nse_ticker,
               SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE 0 END) as bull,
               SUM(CASE WHEN classification IN ('S','SC') THEN 1 ELSE 0 END) as bear,
               COUNT(*) as total
        FROM market_oi_buildup WHERE date IN ({ph})
        GROUP BY nse_ticker
    """, dates).fetchall()
    return {r[0]: {'bull': r[1], 'bear': r[2], 'total': r[3]} for r in rows}


def get_sector_scores(mc, dates, llu_thresh, ssc_thresh):
    """Get bullish and bearish sectors for given dates and thresholds."""
    if not dates:
        return set(), set()
    ph = ','.join('?' * len(dates))
    rows = mc.execute(f"""
        SELECT sector,
               SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE 0 END) as bull,
               SUM(CASE WHEN classification IN ('S','SC') THEN 1 ELSE 0 END) as bear
        FROM market_sector_buildup WHERE date IN ({ph})
        AND sector NOT IN ('NiftyStocks','BankNiftyStocks','FinniftyStocks','NiftyNXT50Stocks','MidcpNiftyStocks')
        GROUP BY sector
    """, dates).fetchall()
    bull = {r[0] for r in rows if r[1] >= llu_thresh}
    bear = {r[0] for r in rows if r[2] >= ssc_thresh}
    return bull, bear


def get_index_scores(mc, dates, llu_thresh, ssc_thresh):
    """Get bullish and bearish indices for given dates and thresholds."""
    index_names = ('NiftyStocks','BankNiftyStocks','FinniftyStocks','NiftyNXT50Stocks','MidcpNiftyStocks')
    if not dates:
        return set(), set()
    ph = ','.join('?' * len(dates))
    placeholders_idx = ','.join('?' * len(index_names))
    rows = mc.execute(f"""
        SELECT sector,
               SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE 0 END) as bull,
               SUM(CASE WHEN classification IN ('S','SC') THEN 1 ELSE 0 END) as bear
        FROM market_sector_buildup WHERE date IN ({ph})
        AND sector IN ({placeholders_idx})
        GROUP BY sector
    """, dates + list(index_names)).fetchall()
    bull = {r[0] for r in rows if r[1] >= llu_thresh}
    bear = {r[0] for r in rows if r[2] >= ssc_thresh}
    return bull, bear


def run_oi_buildup(cfg: dict, as_of_date: Optional[str] = None) -> dict:
    mc = sqlite3.connect(MARKET_DB)
    tc = sqlite3.connect(TRADE_DB)
    try:
        if not as_of_date:
            as_of_date = mc.execute("SELECT MAX(date) FROM market_oi_buildup").fetchone()[0]

        # ── PARAMETERS ──
        c1_days   = int(cfg.get('cycle1_days', 20))
        c1_llu    = int(cfg.get('cycle1_llu', 14))
        c1_ssc    = int(cfg.get('cycle1_ssc', 14))
        c2_days   = int(cfg.get('cycle2_days', 10))
        c2_llu    = int(cfg.get('cycle2_llu', 8))
        c2_ssc    = int(cfg.get('cycle2_ssc', 8))
        hc_days   = int(cfg.get('hc_cycle_days', 10))
        hc_bull   = int(cfg.get('hc_bull_thresh', 9))
        hc_bear   = int(cfg.get('hc_bear_thresh', 9))
        sc1_days  = int(cfg.get('sec_cycle1_days', 20))
        sc1_llu   = int(cfg.get('sec_cycle1_llu', 14))
        sc1_ssc   = int(cfg.get('sec_cycle1_ssc', 14))
        sc2_days  = int(cfg.get('sec_cycle2_days', 10))
        sc2_llu   = int(cfg.get('sec_cycle2_llu', 7))
        sc2_ssc   = int(cfg.get('sec_cycle2_ssc', 8))
        pp_bull   = float(cfg.get('pp_bullish', 90))
        pp_bear   = float(cfg.get('pp_bearish', 10))
        oi_pct    = float(cfg.get('oi_pct', 90))
        ivp_long  = float(cfg.get('ivp_long', 30))

        # ── TRADING DATES ──
        stk_dates_c1  = get_trading_dates(mc, 'market_oi_buildup', as_of_date, c1_days)
        stk_dates_c2  = get_trading_dates(mc, 'market_oi_buildup', as_of_date, c2_days)
        stk_dates_hc  = get_trading_dates(mc, 'market_oi_buildup', as_of_date, hc_days)
        sec_dates_c1  = get_trading_dates(mc, 'market_sector_buildup', as_of_date, sc1_days)
        sec_dates_c2  = get_trading_dates(mc, 'market_sector_buildup', as_of_date, sc2_days)

        # ── STOCK SCORES ──
        sc1 = get_llu_scores(mc, stk_dates_c1)
        sc2 = get_llu_scores(mc, stk_dates_c2)
        hc  = get_llu_scores(mc, stk_dates_hc)

        # ── SECTOR / INDEX CLASSIFICATIONS ──
        bull_sec_c1, bear_sec_c1 = get_sector_scores(mc, sec_dates_c1, sc1_llu, sc1_ssc)
        bull_sec_c2, bear_sec_c2 = get_sector_scores(mc, sec_dates_c2, sc2_llu, sc2_ssc)
        bull_idx_c1, bear_idx_c1 = get_index_scores(mc,  sec_dates_c1, sc1_llu, sc1_ssc)
        bull_idx_c2, bear_idx_c2 = get_index_scores(mc,  sec_dates_c2, sc2_llu, sc2_ssc)

        bull_sectors = bull_sec_c1 | bull_sec_c2
        bear_sectors = bear_sec_c1 | bear_sec_c2
        bull_indices = bull_idx_c1 | bull_idx_c2
        bear_indices = bear_idx_c1 | bear_idx_c2

        # ── MAPPINGS ──
        options_uni  = set(r[0] for r in tc.execute("SELECT nse_ticker FROM stock_master WHERE is_active=1").fetchall())
        sec_map      = {r[0]: r[1] for r in mc.execute("SELECT nse_ticker, sector FROM stock_sector").fetchall()}
        idx_map      = {}
        for r in mc.execute("SELECT nse_ticker, index_name FROM stock_index").fetchall():
            idx_map.setdefault(r[0], set()).add(r[1])

        # ── CORROBORATIVE DATA ──
        cwt = set(r[0] for r in mc.execute(
            "SELECT nse_ticker FROM market_writers_trap WHERE signal_type='CWT' AND date=?", (as_of_date,)).fetchall())
        pwt = set(r[0] for r in mc.execute(
            "SELECT nse_ticker FROM market_writers_trap WHERE signal_type='PWT' AND date=?", (as_of_date,)).fetchall())

        poip = {r[0]: {'pp': r[1], 'oip': r[2]} for r in mc.execute(
            "SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip WHERE date=?", (as_of_date,)).fetchall()}

        pcr_data = {r[0]: {'oi_pcr': r[1], 'vol_pcr': r[2]} for r in mc.execute(
            'SELECT nse_ticker, oi_pcr_curr, vol_pcr_curr FROM market_pcr WHERE date=?', (as_of_date,)).fetchall()}

        iv_data = {r[0]: {'iv': r[1], 'ivp': r[2], 'ivr': r[3]} for r in mc.execute(
            "SELECT nse_ticker, iv, ivp, ivr FROM market_iv WHERE date=?", (as_of_date,)).fetchall()}

        trigger = {r[0]: {
            'futures': r[1], 'call_strike': r[2], 'call_oi': r[3],
            'call_chg_oi_pct': r[4], 'call_diff_pct': r[5],
            'put_strike': r[6], 'put_oi': r[7],
            'put_chg_oi_pct': r[8], 'put_diff_pct': r[9]
        } for r in mc.execute("""
            SELECT nse_ticker, futures_price, call_strike, call_oi, call_chg_oi_pct, call_diff_pct,
                   put_strike, put_oi, put_chg_oi_pct, put_diff_pct
            FROM market_oi_trigger WHERE date=? AND nse_ticker != 'Symbol\nFuture'
        """, (as_of_date,)).fetchall()}

        # ── A+B+C+D+E SUB-LISTS ──
        def build_stock_entry(ticker, direction):
            sector  = sec_map.get(ticker, 'Unknown')
            indices = idx_map.get(ticker, set())
            s_c1    = sc1.get(ticker, {})
            s_c2    = sc2.get(ticker, {})
            s_hc    = hc.get(ticker, {})
            key     = 'bull' if direction == 'Bullish' else 'bear'

            # Sub-list membership
            lists = []
            if s_hc.get(key, 0) >= hc_bull if direction == 'Bullish' else s_hc.get(key, 0) >= hc_bear:
                lists.append('A')
            if s_c2.get(key, 0) >= c2_llu if direction == 'Bullish' else s_c2.get(key, 0) >= c2_ssc:
                sec_match = sector in (bull_sectors if direction == 'Bullish' else bear_sectors)
                if sec_match: lists.append('B')
            if s_c1.get(key, 0) >= c1_llu if direction == 'Bullish' else s_c1.get(key, 0) >= c1_ssc:
                sec_match = sector in (bull_sectors if direction == 'Bullish' else bear_sectors)
                if sec_match: lists.append('C')
            if s_c2.get(key, 0) >= c2_llu if direction == 'Bullish' else s_c2.get(key, 0) >= c2_ssc:
                idx_match = bool(indices & (bull_indices if direction == 'Bullish' else bear_indices))
                if idx_match: lists.append('D')
            if s_c1.get(key, 0) >= c1_llu if direction == 'Bullish' else s_c1.get(key, 0) >= c1_ssc:
                idx_match = bool(indices & (bull_indices if direction == 'Bullish' else bear_indices))
                if idx_match: lists.append('E')

            # Corroborative data
            p  = poip.get(ticker, {})
            iv = iv_data.get(ticker, {})
            tr = trigger.get(ticker, {})
            poip_check = (p.get('pp', 0) >= pp_bull and p.get('oip', 0) >= oi_pct) if direction == 'Bullish' else \
                         (p.get('pp', 100) <= pp_bear and p.get('oip', 0) >= oi_pct)
            trap = ticker in cwt if direction == 'Bullish' else ticker in pwt

            # Score: IVP in range + POIP + Trap
            score = 0
            if poip_check: score += 1
            if trap:       score += 1
            # HCOI/HPOI proximity score
            _hc = float(cfg.get('hcoi_prox_pct', 0.75))
            _hp = float(cfg.get('hpoi_prox_pct', 0.75))
            c_diff = abs(tr.get('call_diff_pct', 99) or 99)
            p_diff = abs(tr.get('put_diff_pct', 99) or 99)
            if direction == 'Bullish':
                if c_diff <= _hc: score += 1
                if p_diff <= _hp: score += 1
            else:
                if p_diff <= _hp: score += 1
                if c_diff <= _hc: score += 1

            return {
                'ticker':         ticker,
                'sector':         sector,
                'indices':        sorted(indices),
                'direction':      direction,
                'instrument':     'Options' if ticker in options_uni else 'Spot',
                'lists':          '+'.join(sorted(set(lists))),
                'c1_score':       f"{s_c1.get(key,0)}/{len(stk_dates_c1)}",
                'c2_score':       f"{s_c2.get(key,0)}/{len(stk_dates_c2)}",
                'hc_score':       f"{s_hc.get(key,0)}/{len(stk_dates_hc)}",
                'futures':        tr.get('futures'),
                'ivp':            iv.get('ivp'),
                'iv':             iv.get('iv'),
                'price_pct':      p.get('pp'),
                'oi_pct':         p.get('oip'),
                'poip_check':     poip_check,
                'trap':           trap,
                'call_strike':    tr.get('call_strike'),
                'call_chg_oi':    tr.get('call_chg_oi_pct'),
                'call_diff':      tr.get('call_diff_pct'),
                'put_strike':     tr.get('put_strike'),
                'put_chg_oi':     tr.get('put_chg_oi_pct'),
                'put_diff':       tr.get('put_diff_pct'),
                'pcr_oi':         pcr_data.get(ticker, {}).get('oi_pcr'),
                'pcr_vol':        pcr_data.get(ticker, {}).get('vol_pcr'),
                'score':          score,
                'date':           as_of_date
            }

        # Build combined list for each direction
        def build_list(direction):
            key = 'bull' if direction == 'Bullish' else 'bear'
            candidates = set()

            # List A: HC standalone
            for t, s in hc.items():
                thresh = hc_bull if direction == 'Bullish' else hc_bear
                if s.get(key, 0) >= thresh:
                    candidates.add(t)

            # Lists B+C: Sector confirmed
            bull_sec = bull_sectors if direction == 'Bullish' else bear_sectors
            for t, s in sc2.items():
                thresh = c2_llu if direction == 'Bullish' else c2_ssc
                if s.get(key, 0) >= thresh and sec_map.get(t) in bull_sec:
                    candidates.add(t)
            for t, s in sc1.items():
                thresh = c1_llu if direction == 'Bullish' else c1_ssc
                if s.get(key, 0) >= thresh and sec_map.get(t) in bull_sec:
                    candidates.add(t)

            # Lists D+E: Index confirmed
            bull_idx = bull_indices if direction == 'Bullish' else bear_indices
            for t, s in sc2.items():
                thresh = c2_llu if direction == 'Bullish' else c2_ssc
                if s.get(key, 0) >= thresh and bool(idx_map.get(t, set()) & bull_idx):
                    candidates.add(t)
            for t, s in sc1.items():
                thresh = c1_llu if direction == 'Bullish' else c1_ssc
                if s.get(key, 0) >= thresh and bool(idx_map.get(t, set()) & bull_idx):
                    candidates.add(t)

            entries = [build_stock_entry(t, direction) for t in candidates if build_stock_entry(t, direction)['lists']]
            return sorted(entries, key=lambda x: (-x['score'], x['ticker']))

        final_bull = build_list('Bullish')
        final_bear = build_list('Bearish')

        # Sector/Index summary for display
        def sector_summary(bull_sec, bear_sec, bull_idx, bear_idx, sc1_dates, sc2_dates):
            result = {'bullish': [], 'bearish': []}
            all_names = bull_sec | bear_sec | bull_idx | bear_idx
            for name in sorted(all_names):
                is_idx = name in ('NiftyStocks','BankNiftyStocks','FinniftyStocks','NiftyNXT50Stocks','MidcpNiftyStocks')
                in_bull = name in (bull_idx if is_idx else bull_sec)
                in_bear = name in (bear_idx if is_idx else bear_sec)
                if in_bull:
                    result['bullish'].append({'name': name, 'type': 'Index' if is_idx else 'Sector'})
                elif in_bear:
                    result['bearish'].append({'name': name, 'type': 'Index' if is_idx else 'Sector'})
            return result

        summary = sector_summary(bull_sectors, bear_sectors, bull_indices, bear_indices, sec_dates_c1, sec_dates_c2)

        return {
            'as_of_date':  as_of_date,
            'summary':     summary,
            'bullish':     final_bull,
            'bearish':     final_bear,
            'counts': {
                'bullish': len(final_bull),
                'bearish': len(final_bear),
                'bull_sectors': len(bull_sectors),
                'bear_sectors': len(bear_sectors),
                'bull_indices': len(bull_indices),
                'bear_indices': len(bear_indices)
            },
            'config': {
                'stock_c1':  f"{c1_days}d L:LU≥{c1_llu} S:SC≥{c1_ssc}",
                'stock_c2':  f"{c2_days}d L:LU≥{c2_llu} S:SC≥{c2_ssc}",
                'hc':        f"{hc_days}d ≥{hc_bull}/{hc_bear}",
                'sector_c1': f"{sc1_days}d ≥{sc1_llu}/{sc1_ssc}",
                'sector_c2': f"{sc2_days}d ≥{sc2_llu}/{sc2_ssc}"
            }
        }
    finally:
        mc.close()
        tc.close()


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("/api/analytics/oi_buildup")
async def oi_buildup_screener(as_of_date: Optional[str] = None):
    try:
        cfg = get_analytics_config()
        result = run_oi_buildup(cfg, as_of_date)
        return {"status": "ok", **result}
    except Exception as e:
        import traceback
        logger.error(f"OI Buildup error: {e}")
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@router.get("/api/analytics/config")
async def analytics_config():
    return get_analytics_config()


@router.get("/api/analytics/breadth")
async def breadth_chart():
    mc = sqlite3.connect(MARKET_DB)
    try:
        rows = mc.execute("""
            SELECT b.date, b.breadth, p.futures_price
            FROM market_breadth b
            LEFT JOIN market_pcr p ON p.date = b.date AND p.nse_ticker = 'NIFTY'
            ORDER BY b.date
        """).fetchall()
        dates    = [r[0] for r in rows]
        breadths = [r[1] for r in rows]
        nifty    = [r[2] for r in rows]
        sma = []
        for i in range(len(breadths)):
            if i < 19:
                sma.append(None)
            else:
                sma.append(round(sum(breadths[i-19:i+1]) / 20, 2))
        signals = []
        for i in range(3, len(sma)):
            if any(x is None for x in [sma[i],sma[i-1],sma[i-2],sma[i-3]]):
                continue
            if sma[i] > sma[i-1] > sma[i-2] and sma[i-2] < sma[i-3]:
                signals.append({'date':dates[i],'type':'BUY','sma':sma[i],'nifty':nifty[i]})
            elif sma[i] < sma[i-1] < sma[i-2] and sma[i-2] > sma[i-3]:
                signals.append({'date':dates[i],'type':'SELL','sma':sma[i],'nifty':nifty[i]})
        sma_z = _zscore(sma)
        nifty_z = _zscore(nifty)
        div = [round(sma_z[i]-nifty_z[i],3) if sma_z[i] is not None and nifty_z[i] is not None else None for i in range(len(sma_z))]
        div_signals = []
        for i in range(2,len(div)):
            if any(x is None for x in [div[i],div[i-1],div[i-2]]): continue
            if div[i]>0 and div[i-1]>0 and div[i-2]<=0:
                div_signals.append({'date':dates[i],'type':'BUY','div':div[i],'nifty':nifty[i]})
            elif div[i]<0 and div[i-1]<0 and div[i-2]>=0:
                div_signals.append({'date':dates[i],'type':'SELL','div':div[i],'nifty':nifty[i]})
        return {'status':'ok','dates':dates,'breadth':breadths,'sma':sma,'nifty':nifty,'sma_z':sma_z,'nifty_z':nifty_z,'div':div,'signals':signals,'div_signals':div_signals,'count':len(dates)}
    except Exception as ex:
        import traceback
        return {'status':'error','error':str(ex),'trace':traceback.format_exc()}
    finally:
        mc.close()


def _zscore(arr):
    vals = [x for x in arr if x is not None]
    if not vals: return arr
    mean = sum(vals)/len(vals)
    std = (sum((x-mean)**2 for x in vals)/len(vals))**0.5
    if std == 0: return [0]*len(arr)
    return [round((x-mean)/std,3) if x is not None else None for x in arr]


@router.get("/api/analytics/writers_trap")
async def writers_trap_screener():
    try:
        cfg = get_analytics_config()
        mc = sqlite3.connect(MARKET_DB)
        tc = sqlite3.connect(TRADE_DB)
        try:
            as_of_date = mc.execute("SELECT MAX(date) FROM market_writers_trap").fetchone()[0]
            c1_days = int(cfg.get("cycle1_days",20)); c1_llu = int(cfg.get("cycle1_llu",14)); c1_ssc = int(cfg.get("cycle1_ssc",14))
            c2_days = int(cfg.get("cycle2_days",10)); c2_llu = int(cfg.get("cycle2_llu",8));  c2_ssc = int(cfg.get("cycle2_ssc",8))
            hcoi_pct = float(cfg.get("hcoi_prox_pct",0.75)); hpoi_pct = float(cfg.get("hpoi_prox_pct",0.75))
            pp_bull = float(cfg.get("pp_bullish",90)); pp_bear = float(cfg.get("pp_bearish",10)); oi_pct = float(cfg.get("oi_pct",90))

            expiry = tc.execute("SELECT expiry_date FROM expiry_calendar WHERE expiry_type=\'MONTHLY\' AND expiry_date >= ? ORDER BY expiry_date LIMIT 1",(as_of_date,)).fetchone()
            expiry_date = expiry[0] if expiry else None
            from datetime import date as _date, timedelta
            holidays = set(r[0] for r in tc.execute("SELECT holiday_date FROM holidays").fetchall())
            _d = _date.fromisoformat(as_of_date)
            _exp = _date.fromisoformat(expiry_date) if expiry_date else _d
            dte = 0
            while _d < _exp:
                _d += timedelta(days=1)
                if _d.weekday() < 5 and _d.isoformat() not in holidays:
                    dte += 1
            phase = "A" if dte <= 5 else "B" if dte <= 10 else "C"
            options_uni = set(r[0] for r in tc.execute("SELECT nse_ticker FROM stock_master WHERE is_active=1").fetchall())
            trig = {r[0]:{"futures":r[1],"call_strike":r[2],"call_diff":r[3],"put_strike":r[4],"put_diff":r[5]} for r in mc.execute("SELECT nse_ticker,futures_price,call_strike,call_diff_pct,put_strike,put_diff_pct FROM market_oi_trigger WHERE date=?", (as_of_date,)).fetchall()}

            dates_in_db = [r[0] for r in mc.execute("SELECT DISTINCT date FROM market_writers_trap ORDER BY date DESC LIMIT 2").fetchall()]
            today_date = dates_in_db[0] if dates_in_db else as_of_date
            prev_date  = dates_in_db[1] if len(dates_in_db) > 1 else None

            sig_dates = [r[0] for r in mc.execute("SELECT DISTINCT signal_date FROM market_writers_trap ORDER BY signal_date DESC LIMIT 2").fetchall()]
            latest_sig = sig_dates[0] if sig_dates else None
            prev_sig = sig_dates[1] if len(sig_dates) > 1 else None
            if phase == "A":
                traps = mc.execute("SELECT nse_ticker, signal_type, return_pct FROM market_writers_trap WHERE signal_date=?",(latest_sig,)).fetchall()
            elif phase == "B":
                if prev_sig:
                    traps = mc.execute("SELECT nse_ticker, signal_type, return_pct FROM market_writers_trap WHERE signal_date IN (?,?)",(latest_sig, prev_sig)).fetchall()
                else:
                    traps = mc.execute("SELECT nse_ticker, signal_type, return_pct FROM market_writers_trap WHERE signal_date=?",(latest_sig,)).fetchall()
            else:
                traps = mc.execute("SELECT nse_ticker, signal_type, return_pct FROM market_writers_trap").fetchall()
            valid = {(r[0], r[1]): r[2] for r in traps}

            stk_c1 = get_llu_scores(mc, get_trading_dates(mc,"market_oi_buildup",as_of_date,c1_days))
            stk_c2 = get_llu_scores(mc, get_trading_dates(mc,"market_oi_buildup",as_of_date,c2_days))
            bull_set = set(); bear_set = set()
            for t,s in stk_c1.items():
                if s["bull"]>=c1_llu: bull_set.add(t)
                if s["bear"]>=c1_ssc: bear_set.add(t)
            for t,s in stk_c2.items():
                if s["bull"]>=c2_llu: bull_set.add(t)
                if s["bear"]>=c2_ssc: bear_set.add(t)

            sec_map = {r[0]:r[1] for r in mc.execute("SELECT nse_ticker,sector FROM stock_sector").fetchall()}
            poip = {r[0]:{"pp":r[1],"oip":r[2]} for r in mc.execute("SELECT nse_ticker,price_percentile,oi_percentile FROM market_poip WHERE date=?",(as_of_date,)).fetchall()}
            iv_d = {r[0]:{"ivp":r[1]} for r in mc.execute("SELECT nse_ticker,ivp FROM market_iv WHERE date=?",(as_of_date,)).fetchall()}
            trig = {r[0]:{"futures":r[1],"call_strike":r[2],"call_chg_oi":r[3],"call_diff":r[4],"put_strike":r[5],"put_chg_oi":r[6],"put_diff":r[7]} for r in mc.execute("SELECT nse_ticker,futures_price,call_strike,call_chg_oi_pct,call_diff_pct,put_strike,put_chg_oi_pct,put_diff_pct FROM market_oi_trigger WHERE date=?",(as_of_date,)).fetchall()}

            cwt=[]; pwt=[]
            for (ticker,sig_type),ret in valid.items():
                is_cwt = "CALL" in sig_type
                key = "bull" if is_cwt else "bear"
                in_cycle = ticker in (bull_set if is_cwt else bear_set)
                s1 = stk_c1.get(ticker,{}); s2 = stk_c2.get(ticker,{})
                p = poip.get(ticker,{}); tr = trig.get(ticker,{})
                poip_ok = (p.get("pp",0)>=pp_bull and p.get("oip",0)>=oi_pct) if is_cwt else (p.get("pp",100)<=pp_bear and p.get("oip",0)>=oi_pct)
                cd = abs(tr.get("call_diff",99) or 99); pd2 = abs(tr.get("put_diff",99) or 99)
                bo_bd = cd<=hcoi_pct if is_cwt else pd2<=hpoi_pct
                pb = pd2<=hpoi_pct if is_cwt else cd<=hcoi_pct
                score = sum([poip_ok, bo_bd, pb])
                entry = {"ticker":ticker,"sector":sec_map.get(ticker,"Unknown"),"instrument":"Options" if ticker in options_uni else "Spot",
                         "direction":"Bullish" if is_cwt else "Bearish","return_pct":ret,"in_cycle":in_cycle,
                         "c1_score":f"{s1.get(key,0)}/{c1_days}","c2_score":f"{s2.get(key,0)}/{c2_days}",
                         "futures":tr.get("futures"),"ivp":iv_d.get(ticker,{}).get("ivp"),
                         "price_pct":p.get("pp"),"oi_pct":p.get("oip"),"poip_check":poip_ok,
                         "call_strike":tr.get("call_strike"),"call_chg_oi":tr.get("call_chg_oi"),"call_diff":tr.get("call_diff"),
                         "put_strike":tr.get("put_strike"),"put_chg_oi":tr.get("put_chg_oi"),"put_diff":tr.get("put_diff"),"score":score}
                if in_cycle:
                    (cwt if is_cwt else pwt).append(entry)

            cwt.sort(key=lambda x:(-x["score"],x["ticker"])); pwt.sort(key=lambda x:(-x["score"],x["ticker"]))
            return {"status":"ok","as_of_date":today_date,"expiry_date":expiry_date,"dte":dte,"phase":phase,"cwt":cwt,"pwt":pwt,"counts":{"cwt":len(cwt),"pwt":len(pwt)}}
        finally:
            mc.close(); tc.close()
    except Exception as ex:
        import traceback
        return {"status":"error","error":str(ex),"trace":traceback.format_exc()}


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


@router.get("/api/analytics/trade_lists/combined")
async def get_combined_trade_list(as_of_date: Optional[str] = None):
    """Combine OI Buildup + POIP + Writers Trap into a single bullish/bearish trade list."""
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
    """Save approved trade list and update account_stocks."""
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


@router.get("/api/analytics/pcrp")
async def pcrp_screener():
    """PCR Percentile screener — mean reversion signals with OI Buildup, POIP, Trap cross-reference."""
    try:
        cfg = get_analytics_config()
        mc = sqlite3.connect(MARKET_DB)
        tc = sqlite3.connect(TRADE_DB)
        try:
            as_of_date = mc.execute("SELECT MAX(date) FROM market_pcr WHERE nse_ticker NOT LIKE '%:%'").fetchone()[0]
            lookback   = int(cfg.get('pcr_lookback', 250))
            pcr_bull   = float(cfg.get('pcr_bullish', 20))   # PCR-P < 20 → bullish reversal
            pcr_bear   = float(cfg.get('pcr_bearish', 80))   # PCR-P > 80 → bearish reversal
            c1_days    = int(cfg.get('cycle1_days', 20)); c1_llu = int(cfg.get('cycle1_llu', 14)); c1_ssc = int(cfg.get('cycle1_ssc', 14))
            c2_days    = int(cfg.get('cycle2_days', 10)); c2_llu = int(cfg.get('cycle2_llu', 8));  c2_ssc = int(cfg.get('cycle2_ssc', 8))
            pp_bull    = float(cfg.get('pp_bullish', 90)); pp_bear = float(cfg.get('pp_bearish', 10)); oi_pct = float(cfg.get('oi_pct', 90))

            # Get today's PCR values
            today_pcr = {r[0]: {'oi_pcr': r[1], 'vol_pcr': r[2]} for r in mc.execute(
                "SELECT nse_ticker, oi_pcr_curr, vol_pcr_curr FROM market_pcr WHERE date=? AND nse_ticker NOT LIKE '%:%'",
                (as_of_date,)).fetchall()}

            # Get last N trading dates for PCR
            pcr_dates = [r[0] for r in mc.execute(
                "SELECT DISTINCT date FROM market_pcr WHERE date <= ? ORDER BY date DESC LIMIT ?",
                (as_of_date, lookback)).fetchall()]

            # Calculate PCR-P for each stock
            pcrp = {}
            if pcr_dates:
                ph = ','.join('?' * len(pcr_dates))
                hist = {}
                for r in mc.execute(f"SELECT nse_ticker, date, oi_pcr_curr FROM market_pcr WHERE date IN ({ph}) AND nse_ticker NOT LIKE '%:%' AND oi_pcr_curr IS NOT NULL", pcr_dates).fetchall():
                    hist.setdefault(r[0], []).append(r[2])
                for ticker, vals in hist.items():
                    today_val = today_pcr.get(ticker, {}).get('oi_pcr')
                    if today_val is not None and len(vals) >= 10:
                        pct = round(sum(1 for v in vals if v < today_val) / len(vals) * 100, 1)
                        pcrp[ticker] = {'pcrp': pct, 'days': len(vals)}

            # OI Buildup cycle
            stk_c1 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c1_days))
            stk_c2 = get_llu_scores(mc, get_trading_dates(mc, 'market_oi_buildup', as_of_date, c2_days))
            bull_set = set(); bear_set = set()
            for t,s in stk_c1.items():
                if s['bull'] >= c1_llu: bull_set.add(t)
                if s['bear'] >= c1_ssc: bear_set.add(t)
            for t,s in stk_c2.items():
                if s['bull'] >= c2_llu: bull_set.add(t)
                if s['bear'] >= c2_ssc: bear_set.add(t)

            # POIP
            poip = {r[0]: {'pp': r[1], 'oip': r[2]} for r in mc.execute(
                "SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip WHERE date=?", (as_of_date,)).fetchall()}

            # Writers Trap
            trap_date = mc.execute("SELECT MAX(signal_date) FROM market_writers_trap").fetchone()[0]
            cwt_set = set(r[0] for r in mc.execute("SELECT nse_ticker FROM market_writers_trap WHERE signal_type='CALL_WRITERS_TRAP' AND signal_date=?", (trap_date,)).fetchall())
            pwt_set = set(r[0] for r in mc.execute("SELECT nse_ticker FROM market_writers_trap WHERE signal_type='PUT_WRITERS_TRAP' AND signal_date=?", (trap_date,)).fetchall())

            # IV
            iv_d = {r[0]: r[1] for r in mc.execute("SELECT nse_ticker, ivp FROM market_iv WHERE date=?", (as_of_date,)).fetchall()}

            sec_map = {r[0]: r[1] for r in mc.execute("SELECT nse_ticker, sector FROM stock_sector").fetchall()}
            options_uni = set(r[0] for r in tc.execute("SELECT nse_ticker FROM stock_master WHERE is_active=1").fetchall())
            trig = {r[0]:{"futures":r[1],"call_strike":r[2],"call_diff":r[3],"put_strike":r[4],"put_diff":r[5]} for r in mc.execute("SELECT nse_ticker,futures_price,call_strike,call_diff_pct,put_strike,put_diff_pct FROM market_oi_trigger WHERE date=?", (as_of_date,)).fetchall()}

            bull_reversal = []
            bear_signal   = []

            for ticker, pcr_data in pcrp.items():
                p = pcr_data['pcrp']
                t_pcr = today_pcr.get(ticker, {})
                t_poip = poip.get(ticker, {})
                in_bull_cycle = ticker in bull_set
                in_bear_cycle = ticker in bear_set
                poip_bull = t_poip.get('pp', 0) >= pp_bull and t_poip.get('oip', 0) >= oi_pct
                poip_bear = t_poip.get('pp', 100) <= pp_bear and t_poip.get('oip', 0) >= oi_pct
                cwt = ticker in cwt_set
                pwt = ticker in pwt_set

                entry = {
                    'ticker':        ticker,
                    'sector':        sec_map.get(ticker, 'Unknown'),
                    'instrument':    'Options' if ticker in options_uni else 'Spot',
                    'pcrp':          p,
                    'oi_pcr':        t_pcr.get('oi_pcr'),
                    'vol_pcr':       t_pcr.get('vol_pcr'),
                    'pcr_days':      pcr_data['days'],
                    'in_bull_cycle': in_bull_cycle,
                    'in_bear_cycle': in_bear_cycle,
                    'poip_bull':     poip_bull,
                    'poip_bear':     poip_bear,
                    'pp':            t_poip.get('pp'),
                    'oip':           t_poip.get('oip'),
                    'cwt':           cwt,
                    'pwt':           pwt,
                    'ivp':           iv_d.get(ticker),
                }

                if p < pcr_bull:
                    bull_reversal.append(entry)
                elif p > pcr_bear:
                    bear_signal.append(entry)

            bull_reversal.sort(key=lambda x: x['pcrp'])
            bear_signal.sort(key=lambda x: -x['pcrp'])

            # ── REVERSAL SIGNALS (3-day crossing logic) ──
            confirm_days = int(cfg.get('pcr_confirm_days', 2))
            # Get last 3 distinct dates
            rev_dates = [r[0] for r in mc.execute(
                'SELECT DISTINCT date FROM market_pcr WHERE date<=? ORDER BY date DESC LIMIT ?',
                (as_of_date, confirm_days+1)).fetchall()]

            if len(rev_dates) >= confirm_days+1:
                today_d = rev_dates[0]
                prev_dates = rev_dates[1:]
                # Get PCR-P for prev dates
                def get_pcrp_for_date(d):
                    day_pcr = {r[0]: r[1] for r in mc.execute(
                        'SELECT nse_ticker, oi_pcr_curr FROM market_pcr WHERE date=? AND nse_ticker IN (SELECT DISTINCT nse_ticker FROM market_oi_buildup)',
                        (d,)).fetchall()}
                    result = {}
                    for ticker, today_val in day_pcr.items():
                        hist = [r[0] for r in mc.execute(
                            'SELECT oi_pcr_curr FROM market_pcr WHERE nse_ticker=? AND date<? AND oi_pcr_curr IS NOT NULL ORDER BY date DESC LIMIT ?',
                            (ticker, d, lookback)).fetchall()]
                        if hist and len(hist) >= 10:
                            result[ticker] = round(sum(1 for v in hist if v < today_val)/len(hist)*100, 1)
                    return result

                prev_pcrp = [get_pcrp_for_date(d) for d in prev_dates]

                bull_reversals = []
                bear_reversals = []
                for ticker in pcrp:
                    today_p = pcrp[ticker]['pcrp']
                    prev_ps = [p.get(ticker) for p in prev_pcrp]
                    if None in prev_ps: continue
                    # Bullish: prev days all <= pcr_bull, today > pcr_bull
                    if all(p <= pcr_bull for p in prev_ps) and today_p > pcr_bull:
                        _tr = trig.get(ticker,{}); _p = poip.get(ticker,{})
                        e = {'ticker':ticker,'sector':sec_map.get(ticker,'Unknown'),'instrument':'Options' if ticker in options_uni else 'Spot',
                             'pcrp':today_p,'prev_pcrp':prev_ps,'oi_pcr':today_pcr.get(ticker,{}).get('oi_pcr'),
                             'pcr_days':pcrp[ticker]['days'],'in_bull_cycle':ticker in bull_set,'in_bear_cycle':ticker in bear_set,
                             'cwt':ticker in cwt_set,'pwt':ticker in pwt_set,'ivp':iv_d.get(ticker),
                             'pp':_p.get('pp'),'oip':_p.get('oip'),
                             'call_strike':_tr.get('call_strike'),'call_diff':_tr.get('call_diff'),
                             'put_strike':_tr.get('put_strike'),'put_diff':_tr.get('put_diff'),'futures':_tr.get('futures')}
                        bull_reversals.append(e)
                    # Bearish: prev days all >= pcr_bear, today < pcr_bear
                    elif all(p >= pcr_bear for p in prev_ps) and today_p < pcr_bear:
                        _tr = trig.get(ticker,{}); _p = poip.get(ticker,{})
                        e = {'ticker':ticker,'sector':sec_map.get(ticker,'Unknown'),'instrument':'Options' if ticker in options_uni else 'Spot',
                             'pcrp':today_p,'prev_pcrp':prev_ps,'oi_pcr':today_pcr.get(ticker,{}).get('oi_pcr'),
                             'pcr_days':pcrp[ticker]['days'],'in_bull_cycle':ticker in bull_set,'in_bear_cycle':ticker in bear_set,
                             'cwt':ticker in cwt_set,'pwt':ticker in pwt_set,'ivp':iv_d.get(ticker),
                             'pp':_p.get('pp'),'oip':_p.get('oip'),
                             'call_strike':_tr.get('call_strike'),'call_diff':_tr.get('call_diff'),
                             'put_strike':_tr.get('put_strike'),'put_diff':_tr.get('put_diff'),'futures':_tr.get('futures')}
                        bear_reversals.append(e)
            else:
                bull_reversals = []
                bear_reversals = []

            return {
                'status':         'ok',
                'as_of_date':     as_of_date,
                'lookback_days':  lookback,
                'thresholds':     {'bull': pcr_bull, 'bear': pcr_bear},
                'bull_reversal':  bull_reversal,
                'bear_signal':    bear_signal,
                'bull_reversals': bull_reversals if 'bull_reversals' in dir() else [],
                'bear_reversals': bear_reversals if 'bear_reversals' in dir() else [],
                'counts':         {'bull': len(bull_reversal), 'bear': len(bear_signal), 'bull_rev': len(bull_reversals) if 'bull_reversals' in dir() else 0, 'bear_rev': len(bear_reversals) if 'bear_reversals' in dir() else 0}
            }
        finally:
            mc.close(); tc.close()
    except Exception as ex:
        import traceback
        return {'status': 'error', 'error': str(ex), 'trace': traceback.format_exc()}
