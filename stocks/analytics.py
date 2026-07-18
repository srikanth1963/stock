"""
analytics.py — SMB Algo Analytics Engine
OI Buildup Screener: Index + Sector Filter → Stock Filter → Part A + Part B → Final List
"""
import sqlite3
import logging
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter

logger = logging.getLogger(__name__)

MARKET_DB = "/opt/smb-algo-stocks/market_data.db"
TRADE_DB  = "/opt/smb-algo-stocks/trade.db"

router = APIRouter()


# ── Config loader ─────────────────────────────────────────────────────────────

def get_analytics_config() -> dict:
    mc = sqlite3.connect(MARKET_DB)
    try:
        rows = mc.execute("SELECT key, value FROM analytics_config").fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        mc.close()


# ── Buildup Filter (shared for both sector and index) ─────────────────────────

def classify_buildup(mc, table, group_col, date_col, lookback, llu_thresh, ssc_thresh, as_of_date):
    """Generic cycle classifier for sector or index buildup table."""
    rows = mc.execute(f"""
        SELECT {group_col},
               COUNT(*) as total_days,
               SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE 0 END) as bull_days,
               SUM(CASE WHEN classification IN ('S','SC') THEN 1 ELSE 0 END) as bear_days
        FROM {table}
        WHERE {date_col} <= ? AND {date_col} > date(?, '-{lookback} days')
        GROUP BY {group_col}
    """, (as_of_date, as_of_date)).fetchall()

    result = {}
    for r in rows:
        name, total, bull, bear = r
        if bull >= llu_thresh:
            result[name] = {'classification': 'bullish', 'bull': bull, 'bear': bear, 'total': total}
        elif bear >= ssc_thresh:
            result[name] = {'classification': 'bearish', 'bull': bull, 'bear': bear, 'total': total}
        else:
            result[name] = {'classification': 'neutral', 'bull': bull, 'bear': bear, 'total': total}
    return result


def combine_cycles(c1_class, c2_class, group_name='sector'):
    """Combine long and short cycle results. Short cycle prevails on conflict."""
    all_names = set(c1_class) | set(c2_class)
    bullish = []
    bearish = []

    for name in sorted(all_names):
        c1 = c1_class.get(name, {}).get('classification', 'neutral')
        c2 = c2_class.get(name, {}).get('classification', 'neutral')

        if c1 == 'neutral' and c2 == 'neutral':
            continue

        entry = {group_name: name, 'c1': c1, 'c2': c2, 'reversal': False}

        if c1 == 'bullish' and c2 == 'bullish':
            entry['cycle'] = 'Both'; entry['direction'] = 'Bullish'
            bullish.append(entry)
        elif c1 == 'bearish' and c2 == 'bearish':
            entry['cycle'] = 'Both'; entry['direction'] = 'Bearish'
            bearish.append(entry)
        elif c1 == 'bullish' and c2 == 'neutral':
            entry['cycle'] = 'Long'; entry['direction'] = 'Bullish'
            bullish.append(entry)
        elif c2 == 'bullish' and c1 == 'neutral':
            entry['cycle'] = 'Short'; entry['direction'] = 'Bullish'
            bullish.append(entry)
        elif c1 == 'bearish' and c2 == 'neutral':
            entry['cycle'] = 'Long'; entry['direction'] = 'Bearish'
            bearish.append(entry)
        elif c2 == 'bearish' and c1 == 'neutral':
            entry['cycle'] = 'Short'; entry['direction'] = 'Bearish'
            bearish.append(entry)
        elif c1 == 'bullish' and c2 == 'bearish':
            # Conflict: short prevails → Bearish Reversal
            entry['cycle'] = 'Short'; entry['direction'] = 'Bearish'; entry['reversal'] = True
            bearish.append(entry)
        elif c1 == 'bearish' and c2 == 'bullish':
            # Conflict: short prevails → Bullish Reversal
            entry['cycle'] = 'Short'; entry['direction'] = 'Bullish'; entry['reversal'] = True
            bullish.append(entry)

    return bullish, bearish


# ── Main Screener ─────────────────────────────────────────────────────────────

def run_oi_buildup(cfg: dict, as_of_date: Optional[str] = None) -> dict:
    mc = sqlite3.connect(MARKET_DB)
    tc = sqlite3.connect(TRADE_DB)
    try:
        # Get latest date
        if not as_of_date:
            as_of_date = mc.execute("SELECT MAX(date) FROM market_oi_buildup").fetchone()[0]

        c1_days = int(cfg.get('cycle1_days', 20))
        c1_llu  = int(cfg.get('cycle1_llu', 14))
        c1_ssc  = int(cfg.get('cycle1_ssc', 14))
        c2_days = int(cfg.get('cycle2_days', 10))
        c2_llu  = int(cfg.get('cycle2_llu', 7))
        c2_ssc  = int(cfg.get('cycle2_ssc', 8))
        hc_llu  = int(cfg.get('hc_llu', 9))
        hc_ssc  = int(cfg.get('hc_ssc', 9))
        pp_bullish = float(cfg.get('pp_bullish', 90))
        pp_bearish = float(cfg.get('pp_bearish', 10))
        oi_pct     = float(cfg.get('oi_pct', 90))

        # ── SECTOR FILTER ──
        sec_c1 = classify_buildup(mc, 'market_sector_buildup', 'sector', 'date',
                                   c1_days, c1_llu, c1_ssc, as_of_date)
        sec_c2 = classify_buildup(mc, 'market_sector_buildup', 'sector', 'date',
                                   c2_days, c2_llu, c2_ssc, as_of_date)

        # Separate index entries from sector entries
        index_names = {'NiftyStocks', 'BankNiftyStocks', 'FinniftyStocks', 'NiftyNXT50Stocks', 'MidcapNiftyStocks'}

        def split_index_sector(c1, c2):
            ic1 = {k: v for k, v in c1.items() if k in index_names}
            ic2 = {k: v for k, v in c2.items() if k in index_names}
            sc1 = {k: v for k, v in c1.items() if k not in index_names}
            sc2 = {k: v for k, v in c2.items() if k not in index_names}
            return ic1, ic2, sc1, sc2

        ic1, ic2, sc1, sc2 = split_index_sector(sec_c1, sec_c2)

        bull_indices, bear_indices   = combine_cycles(ic1, ic2, group_name='index')
        bull_sectors, bear_sectors   = combine_cycles(sc1, sc2, group_name='sector')

        bullish_index_names = {e['index'] for e in bull_indices}
        bearish_index_names = {e['index'] for e in bear_indices}
        bullish_sector_names = {e['sector'] for e in bull_sectors}
        bearish_sector_names = {e['sector'] for e in bear_sectors}

        # ── STOCK MAPPINGS ──
        options_universe = set(r[0] for r in tc.execute(
            "SELECT nse_ticker FROM stock_master WHERE is_active=1").fetchall())
        stock_sector_map = {r[0]: r[1] for r in mc.execute(
            "SELECT nse_ticker, sector FROM stock_sector").fetchall()}
        stock_index_map = {}
        for r in mc.execute("SELECT nse_ticker, index_name FROM stock_index").fetchall():
            stock_index_map.setdefault(r[0], set()).add(r[1])

        # ── WRITERS TRAP ──
        cwt_stocks = set(r[0] for r in mc.execute(
            "SELECT nse_ticker FROM market_writers_trap WHERE signal_type='CWT' AND date=?",
            (as_of_date,)).fetchall())
        pwt_stocks = set(r[0] for r in mc.execute(
            "SELECT nse_ticker FROM market_writers_trap WHERE signal_type='PWT' AND date=?",
            (as_of_date,)).fetchall())

        # ── POIP ──
        poip_data = {r[0]: {'pp': r[1], 'oip': r[2]} for r in mc.execute(
            "SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip WHERE date=?",
            (as_of_date,)).fetchall()}

        # ── STOCK CYCLE SCORES ──
        def get_scores(lookback):
            rows = mc.execute(f"""
                SELECT nse_ticker,
                       COUNT(*) as total,
                       SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE 0 END) as bull,
                       SUM(CASE WHEN classification IN ('S','SC') THEN 1 ELSE 0 END) as bear
                FROM market_oi_buildup
                WHERE date <= ? AND date > date(?, '-{lookback} days')
                GROUP BY nse_ticker
            """, (as_of_date, as_of_date)).fetchall()
            return {r[0]: {'total': r[1], 'bull': r[2], 'bear': r[3]} for r in rows}

        sc1_scores = get_scores(c1_days)
        sc2_scores = get_scores(c2_days)

        # ── INITIAL FILTER ──
        initial_bull = set()
        initial_bear = set()
        for t, s in sc1_scores.items():
            if s['bull'] >= c1_llu: initial_bull.add(t)
            if s['bear'] >= c1_ssc: initial_bear.add(t)
        for t, s in sc2_scores.items():
            if s['bull'] >= c2_llu: initial_bull.add(t)
            if s['bear'] >= c2_ssc: initial_bear.add(t)

        # ── HIGH CONVICTION (standalone, uses c2_days lookback) ──
        hc_bull = {t for t, s in sc2_scores.items() if s['bull'] >= hc_llu}
        hc_bear = {t for t, s in sc2_scores.items() if s['bear'] >= hc_ssc}

        # ── BUILD ENTRY ──
        def build_entry(ticker, direction):
            sector = stock_sector_map.get(ticker, 'Unknown')
            indices = stock_index_map.get(ticker, set())
            s1 = sc1_scores.get(ticker, {})
            s2 = sc2_scores.get(ticker, {})
            key = 'bull' if direction == 'Bullish' else 'bear'
            return {
                'ticker': ticker,
                'sector': sector,
                'indices': sorted(indices),
                'direction': direction,
                'instrument': 'Options' if ticker in options_universe else 'Spot',
                'c1_score': f"{s1.get(key,0)}/{c1_days}",
                'c2_score': f"{s2.get(key,0)}/{c2_days}",
                'part_a': False,
                'part_a_reason': '',
                'part_b_trap': False,
                'part_b_poip': False,
                'high_conviction': ticker in (hc_bull if direction == 'Bullish' else hc_bear),
                'date': as_of_date
            }

        # ── PART A ──
        # Sector confirmed OR Index confirmed OR High Conviction standalone
        part_a_bull, part_a_bear = [], []

        for t in initial_bull:
            sector = stock_sector_map.get(t)
            indices = stock_index_map.get(t, set())
            sector_match = sector and sector in bullish_sector_names
            index_match = bool(indices & bullish_index_names)
            hc_match = t in hc_bull
            if sector_match or index_match or hc_match:
                e = build_entry(t, 'Bullish')
                e['part_a'] = True
                reasons = []
                if sector_match: reasons.append('Sector')
                if index_match: reasons.append('Index')
                if hc_match: reasons.append('HC')
                e['part_a_reason'] = '+'.join(reasons)
                part_a_bull.append(e)

        for t in initial_bear:
            sector = stock_sector_map.get(t)
            indices = stock_index_map.get(t, set())
            sector_match = sector and sector in bearish_sector_names
            index_match = bool(indices & bearish_index_names)
            hc_match = t in hc_bear
            if sector_match or index_match or hc_match:
                e = build_entry(t, 'Bearish')
                e['part_a'] = True
                reasons = []
                if sector_match: reasons.append('Sector')
                if index_match: reasons.append('Index')
                if hc_match: reasons.append('HC')
                e['part_a_reason'] = '+'.join(reasons)
                part_a_bear.append(e)

        # ── PART B ──
        part_b_bull, part_b_bear = [], []

        # B1: Writers Trap
        for t in initial_bull:
            if t in cwt_stocks:
                e = build_entry(t, 'Bullish')
                e['part_b_trap'] = True
                part_b_bull.append(e)
        for t in initial_bear:
            if t in pwt_stocks:
                e = build_entry(t, 'Bearish')
                e['part_b_trap'] = True
                part_b_bear.append(e)

        # B2: POIP
        for t in initial_bull:
            p = poip_data.get(t, {})
            if p.get('pp', 0) >= pp_bullish and p.get('oip', 0) >= oi_pct:
                e = build_entry(t, 'Bullish')
                e['part_b_poip'] = True
                part_b_bull.append(e)
        for t in initial_bear:
            p = poip_data.get(t, {})
            if p.get('pp', 0) <= pp_bearish and p.get('oip', 0) >= oi_pct:
                e = build_entry(t, 'Bearish')
                e['part_b_poip'] = True
                part_b_bear.append(e)

        # ── COMBINE & DEDUPLICATE ──
        def combine(part_a, part_b):
            combined = {}
            for e in part_a:
                combined[e['ticker']] = dict(e)
            for e in part_b:
                t = e['ticker']
                if t in combined:
                    combined[t]['part_b_trap'] = combined[t].get('part_b_trap') or e.get('part_b_trap')
                    combined[t]['part_b_poip'] = combined[t].get('part_b_poip') or e.get('part_b_poip')
                else:
                    combined[t] = dict(e)
            return sorted(combined.values(), key=lambda x: x['ticker'])

        final_bull = combine(part_a_bull, part_b_bull)
        final_bear = combine(part_a_bear, part_b_bear)

        return {
            'as_of_date': as_of_date,
            'indices': {
                'bullish': bull_indices,
                'bearish': bear_indices
            },
            'sectors': {
                'bullish': bull_sectors,
                'bearish': bear_sectors
            },
            'stocks': {
                'initial_bullish_count': len(initial_bull),
                'initial_bearish_count': len(initial_bear),
                'final_bullish': final_bull,
                'final_bearish': final_bear
            },
            'config': {
                'cycle1_days': c1_days, 'cycle1_llu': c1_llu, 'cycle1_ssc': c1_ssc,
                'cycle2_days': c2_days, 'cycle2_llu': c2_llu, 'cycle2_ssc': c2_ssc,
                'hc_llu': hc_llu, 'hc_ssc': hc_ssc,
                'pp_bullish': pp_bullish, 'pp_bearish': pp_bearish, 'oi_pct': oi_pct
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
