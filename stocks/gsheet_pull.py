import sqlite3, csv, io, urllib.request
from datetime import datetime, date

SHEET_ID  = "1Kk41WTyE6s2lJO1WJwN0Sh7gEkDvxkAIP1pOswXNo8o"
TRADE_DB  = "/opt/smb-algo-stocks/trade.db"
MARKET_DB = "/opt/smb-algo-stocks/market_data.db"
RETAIN = {"market_poip":300,"market_iv":300,"market_pcr":300,"market_oi_buildup":35,"market_sector_buildup":35}

def fetch_tab(tab):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={tab}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return list(csv.reader(io.StringIO(r.read().decode("utf-8"))))
    except Exception as e:
        print(f"  ERROR fetching {tab}: {e}"); return []

def parse_date(s):
    s = s.strip()
    for fmt in ("%d-%b-%Y","%d-%b-%y","%m/%d/%Y","%d-%m-%Y","%d-%m-%y","%Y-%m-%d","%d/%m/%Y","%d %b %Y","%d %B %Y"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except: pass
    return None

def parse_float(s):
    try: return float(str(s).strip().replace("%","").replace(",","").replace(" ",""))
    except: return None

def purge(conn, table, days):
    conn.execute('DELETE FROM ' + table + " WHERE date < DATE('now', '-" + str(days) + " days')")

def get_known_tickers():
    try:
        conn = sqlite3.connect(TRADE_DB)
        t = {r[0] for r in conn.execute("SELECT nse_ticker FROM stock_master")}
        conn.close(); return t
    except: return set()

def pull_superset(tc):
    print("Pulling SuperSet...")
    rows = fetch_tab("SuperSet")
    if not rows: return
    tc.execute("UPDATE stock_master SET is_active = 0")
    count = 0
    for row in rows[1:]:
        if row and row[0].strip():
            tc.execute("UPDATE stock_master SET is_active = 1 WHERE nse_ticker = ?", (row[0].strip(),))
            count += 1
    tc.commit(); print(f"  {count} active tickers marked")

def pull_accconfig(tc):
    print("Pulling AccConfig...")
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1651782372"
    import urllib.request, csv, io
    with urllib.request.urlopen(url, timeout=15) as r:
        rows = list(csv.reader(io.StringIO(r.read().decode("utf-8"))))
    if not rows: return
    labels = [r[0].strip() if r else "" for r in rows]
    def get_row(label):
        for i,l in enumerate(labels):
            if label.lower() in l.lower(): return rows[i]
        return None
    num_acc = len([c for c in (rows[0] if rows else [])[1:] if c.strip()])
    tc.execute("DELETE FROM account_config"); tc.execute("DELETE FROM account_stocks")
    for col in range(1, num_acc+1):
        def gv(label):
            row = get_row(label)
            return row[col].strip() if row and col < len(row) else ""
        status = gv("Status")
        if not status: continue
        capital = parse_float(gv("Capital")) or 0
        ml_pct = parse_float(gv("Max loss")) or 15
        tc.execute("INSERT INTO account_config (account_name,account_type,dp_name,capital_allocation,max_daily_loss,lots_per_trade,status) VALUES (?,?,?,?,?,?,?)",
            (gv("Name"),gv("Account Type"),gv("Account Name in DP"),capital,capital*(ml_pct/100),int(parse_float(gv("Number of lots")) or 1),status))
        acc_id = tc.execute("SELECT last_insert_rowid()").fetchone()[0]
        for row in rows:
            lbl = row[0].strip() if row else ""
            if lbl.lower().startswith("stock") and col < len(row) and row[col].strip():
                tc.execute("INSERT OR IGNORE INTO account_stocks (account_id,nse_ticker) VALUES (?,?)",(acc_id,row[col].strip()))
    tc.commit()
    print(f"  {tc.execute("SELECT COUNT(*) FROM account_config").fetchone()[0]} accounts, {tc.execute("SELECT COUNT(*) FROM account_stocks").fetchone()[0]} stock assignments loaded")

def pull_holidays(tc):
    print("Pulling Holidays...")
    rows = fetch_tab("Holidays")
    if not rows: return
    tc.execute("DELETE FROM holidays")
    count = 0
    for row in rows[1:]:
        if not row or not row[1].strip(): continue
        d = parse_date(row[1])
        if d:
            tc.execute("INSERT OR IGNORE INTO holidays (holiday_date,description) VALUES (?,?)",(d,row[3].strip() if len(row)>3 else ""))
            count += 1
    tc.commit(); print(f"  {count} holidays loaded")

def pull_expiry(tc):
    print("Pulling Expiry...")
    rows = fetch_tab("Expiry")
    if not rows: return
    tc.execute("DELETE FROM expiry_calendar")
    count = 0
    for row in rows[1:]:
        if not row or not row[0].strip(): continue
        d = parse_date(row[0]); etype = row[2].strip().upper() if len(row)>2 else "MONTHLY"
        expiry_type = "WEEKLY" if etype == "WEEKLY" else "MONTHLY"
        if d:
            tc.execute("INSERT OR IGNORE INTO expiry_calendar (expiry_date,expiry_type,underlying) VALUES (?,?,?)",(d,expiry_type,"ALL"))
            count += 1
    tc.commit(); print(f"  {count} expiry dates loaded")

def pull_results(tc):
    print("Pulling Results...")
    rows = fetch_tab("Result")
    if not rows: return
    tc.execute("DELETE FROM results_calendar")
    count = 0
    for row in rows[1:]:
        if not row or not row[0].strip(): continue
        d = parse_date(row[0])
        ticker = row[1].strip() if len(row)>1 else None
        if ticker and d:
            tc.execute("INSERT OR IGNORE INTO results_calendar (nse_ticker,result_date) VALUES (?,?)",(ticker,d))
            count += 1
    tc.commit(); print(f"  {count} result dates loaded")

def pull_poip(mc):
    print("Pulling POIP...")
    rows = fetch_tab("POIP")
    if not rows: return
    today = parse_date(rows[0][2]) if rows[0] and len(rows[0])>2 and rows[0][2].strip() else date.today().strftime("%Y-%m-%d")
    count = 0
    for row in rows[1:]:
        if len(row)<7 or not row[4].strip(): continue
        ticker = row[4].strip()
        pp = parse_float(row[5]); op = parse_float(row[6])
        if ticker and pp is not None:
            mc.execute("INSERT OR REPLACE INTO market_poip (date,nse_ticker,price_percentile,oi_percentile) VALUES (?,?,?,?)",(today,ticker,pp,op))
            count += 1
    purge(mc,"market_poip",RETAIN["market_poip"]); mc.commit(); print(f"  {count} POIP records loaded")

def pull_iv(mc):
    print("Pulling IV...")
    rows = fetch_tab("IV")
    if not rows: return
    today = parse_date(rows[0][2]) if rows[0] and len(rows[0])>2 and rows[0][2].strip() else date.today().strftime("%Y-%m-%d")
    count = 0
    known = get_known_tickers()
    bad_tokens = ("N/A", "#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#ERROR!")
    for row in rows[1:]:
        if len(row)<10 or not row[4].strip(): continue
        ticker = row[4].strip()
        if ticker.startswith("#") or ticker.upper() in bad_tokens: continue
        if ticker not in known: continue
        price = parse_float(row[5])
        if price is None: continue
        mc.execute("INSERT OR REPLACE INTO market_iv (date,nse_ticker,price,iv,hv,ivr,ivp) VALUES (?,?,?,?,?,?,?)",
            (today,ticker,price,
             parse_float(row[6]),parse_float(row[7]),
             parse_float(row[8]),parse_float(row[9])))
        count += 1
    purge(mc,"market_iv",RETAIN["market_iv"]); mc.commit(); print(f"  {count} IV records loaded")

def pull_pcr(mc):
    print("Pulling PCR...")
    rows = fetch_tab("PCR")
    if not rows: return
    today = parse_date(rows[0][0]) if rows[0] and rows[0][0].strip() else date.today().strftime("%Y-%m-%d")
    known = get_known_tickers(); count = 0
    for row in rows[2:]:
        if not row or not row[3].strip(): continue
        combined = row[3].strip(); ticker = None; fp = None
        for t in sorted(known, key=len, reverse=True):
            if combined.upper().startswith(t.upper()):
                ticker = t; fp = parse_float(combined[len(t):].replace(",","")); break
        if not ticker:
            parts = combined.rsplit(" ",1); ticker = parts[0].strip()
            fp = parse_float(parts[1]) if len(parts)>1 else None
        if ticker:
            mc.execute("INSERT OR REPLACE INTO market_pcr (date,nse_ticker,futures_price,oi_pcr_prev,oi_pcr_curr,oi_pcr_chg_pct,vol_pcr_prev,vol_pcr_curr,vol_pcr_chg_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (today,ticker,fp,parse_float(row[0]),parse_float(row[1]),parse_float(row[2]),
                 parse_float(row[4]) if len(row)>4 else None,parse_float(row[5]) if len(row)>5 else None,parse_float(row[6]) if len(row)>6 else None))
            count += 1
    purge(mc,"market_pcr",RETAIN["market_pcr"]); mc.commit(); print(f"  {count} PCR records loaded")

def pull_trigger(mc):
    print("Pulling Trigger...")
    rows = fetch_tab("Trigger")
    if not rows: return
    today = parse_date(rows[0][0]) if rows[0] and rows[0][0].strip() else date.today().strftime("%Y-%m-%d")
    known = get_known_tickers(); count = 0
    for row in rows[2:]:
        if not row or not row[4].strip(): continue
        combined = row[4].strip(); ticker = None; fp = None
        for t in sorted(known, key=len, reverse=True):
            if combined.upper().startswith(t.upper()):
                ticker = t; fp = parse_float(combined[len(t):].replace(",","")); break
        if not ticker:
            parts = combined.rsplit(" ",1); ticker = parts[0].strip()
            fp = parse_float(parts[1]) if len(parts)>1 else None
        if ticker:
            mc.execute("INSERT OR REPLACE INTO market_oi_trigger (date,nse_ticker,futures_price,call_strike,call_oi,call_chg_oi_pct,call_diff_pct,put_strike,put_oi,put_chg_oi_pct,put_diff_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (today,ticker,fp,parse_float(row[3]),parse_float(row[1]),parse_float(row[0]),parse_float(row[2]),
                 parse_float(row[5]) if len(row)>5 else None,parse_float(row[7]) if len(row)>7 else None,
                 parse_float(row[8]) if len(row)>8 else None,parse_float(row[6]) if len(row)>6 else None))
            count += 1
    mc.commit(); print(f"  {count} Trigger records loaded")

def pull_trap(mc):
    print("Pulling Trap...")
    rows = fetch_tab("Trap")
    if not rows: return
    today = parse_date(rows[0][0]) if rows[0] and rows[0][0].strip() else date.today().strftime("%Y-%m-%d"); count = 0
    for row in rows[2:]:
        if not row or not row[0].strip(): continue
        sig = row[0].strip().upper().replace(" ","_")
        ticker = row[1].strip() if len(row)>1 else None
        if ticker and sig in ("PUT_WRITERS_TRAP","CALL_WRITERS_TRAP"):
            mc.execute("INSERT OR REPLACE INTO market_writers_trap (date,nse_ticker,signal_type,signal_price,signal_date,close_price,return_pct) VALUES (?,?,?,?,?,?,?)",
                (today,ticker,sig,parse_float(row[2]) if len(row)>2 else None,
                 parse_date(row[3]) if len(row)>3 else None,parse_float(row[4]) if len(row)>4 else None,
                 parse_float(row[5]) if len(row)>5 else None))
            count += 1
    mc.commit(); print(f"  {count} Writers Trap records loaded")

def pull_bu_stk(mc):
    print("Pulling BU_STK...")
    rows = fetch_tab("BU_STK")
    if not rows or len(rows)<3: return
    today = parse_date(rows[0][0]) if rows[0] and rows[0][0].strip() else date.today().strftime("%Y-%m-%d")
    valid = {"L","S","LU","SC"}; count = 0
    for row in rows[2:]:
        if not row or not row[0].strip(): continue
        cls = row[0].strip().upper(); ticker = row[1].strip() if len(row)>1 else ""
        if cls not in valid or not ticker: continue
        mc.execute("INSERT OR REPLACE INTO market_oi_buildup (date,nse_ticker,classification,price_chg_pct,oi_chg_pct) VALUES (?,?,?,?,?)",
            (today,ticker,cls,parse_float(row[4]) if len(row)>4 else None,parse_float(row[5]) if len(row)>5 else None))
        count += 1
    purge(mc,"market_oi_buildup",RETAIN["market_oi_buildup"]); mc.commit(); print(f"  {count} Stock OI Buildup records loaded")

def pull_bu_sector(mc):
    print("Pulling BU_Sector...")
    rows = fetch_tab("BU_Sector")
    if not rows: return
    today = parse_date(rows[0][0]) if rows[0] and rows[0][0].strip() else date.today().strftime("%Y-%m-%d")
    cls_map = {"LONG UNWINDING":"LU","SHORT COVERING":"SC","LONG":"L","SHORT":"S"}
    skip = {"SYMBOL","NARRATION","PRICE","OI","NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"}
    cur_cls = None; count = 0
    for row in rows[1:]:
        if not row or not row[0].strip(): continue
        cell = row[0].strip().upper()
        matched = next((cls_map[k] for k in sorted(cls_map,key=len,reverse=True) if k in cell), None)
        if matched: cur_cls = matched; continue
        if cell in skip: continue
        if cur_cls:
            mc.execute("INSERT OR REPLACE INTO market_sector_buildup (date,sector,classification,price_chg_pct,oi_chg_pct) VALUES (?,?,?,?,?)",
                (today,row[0].strip(),cur_cls,parse_float(row[1]) if len(row)>1 else None,parse_float(row[2]) if len(row)>2 else None))
            count += 1
    purge(mc,"market_sector_buildup",RETAIN["market_sector_buildup"]); mc.commit(); print(f"  {count} Sector OI Buildup records loaded")


def pull_sector_stock(mc):
    print("Pulling Sector-Stock...")
    rows = fetch_tab("Sector-Stock")
    if not rows: return
    mc.execute("DELETE FROM stock_sector")
    count = 0
    for row in rows[1:]:
        if not row or not row[0].strip() or not row[1].strip(): continue
        sector = row[0].strip()
        ticker = row[1].strip()
        mc.execute("INSERT OR IGNORE INTO stock_sector (nse_ticker, sector) VALUES (?,?)", (ticker, sector))
        count += 1
    mc.commit()
    print(f"  {count} sector-stock mappings loaded")

def pull_index_stock(mc):
    print("Pulling Index-Stock...")
    rows = fetch_tab("Index-Stock")
    if not rows: return
    mc.execute("DELETE FROM stock_index")
    count = 0
    for row in rows[1:]:
        if not row or not row[0].strip() or not row[1].strip(): continue
        index_name = row[0].strip()
        ticker = row[1].strip()
        mc.execute("INSERT OR IGNORE INTO stock_index (nse_ticker, index_name) VALUES (?,?)", (ticker, index_name))
        count += 1
    mc.commit()
    print(f"  {count} index-stock mappings loaded")


def pull_breadth(mc):
    """Calculate daily breadth from market_oi_buildup and store in market_breadth."""
    print("Updating market breadth...")
    rows = mc.execute("""
        SELECT date,
               SUM(CASE WHEN classification='L' THEN 1 ELSE 0 END),
               SUM(CASE WHEN classification='LU' THEN 1 ELSE 0 END),
               SUM(CASE WHEN classification='S' THEN 1 ELSE 0 END),
               SUM(CASE WHEN classification='SC' THEN 1 ELSE 0 END),
               SUM(CASE WHEN classification IN ('L','LU') THEN 1 ELSE -1 END)
        FROM market_oi_buildup GROUP BY date
    """).fetchall()
    mc.executemany('INSERT OR IGNORE INTO market_breadth (date,long_count,lu_count,short_count,sc_count,breadth) VALUES (?,?,?,?,?,?)', rows)
    mc.commit()
    print(f'  {len(rows)} breadth records updated')


def pull_analytics(mc):
    print("Pulling Analytics config...")
    rows = fetch_tab("Analytics")
    if not rows or len(rows) < 17:
        print("  Analytics tab missing or incomplete")
        return
    try:
        mc.execute("""CREATE TABLE IF NOT EXISTS analytics_config (
            key TEXT PRIMARY KEY,
            value REAL,
            description TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        mc.commit()

        # Fixed row positions (0-indexed)
        mapping = [
            (2,  'cycle1_days',   'Cycle 1 lookback days'),
            (3,  'cycle1_llu',    'Cycle 1 L:LU threshold (Bullish)'),
            (4,  'cycle1_ssc',    'Cycle 1 S:SC threshold (Bearish)'),
            (5,  'cycle2_days',   'Cycle 2 lookback days'),
            (6,  'cycle2_llu',    'Cycle 2 L:LU threshold (Bullish)'),
            (7,  'cycle2_ssc',    'Cycle 2 S:SC threshold (Bearish)'),
            (8,  'pp_bearish',    'Price Percentile less than (Bearish)'),
            (9,  'pp_bullish',    'Price Percentile more than (Bullish)'),
            (10, 'oi_pct',        'OI Percentile more than (Both)'),
            (11, 'ivp_writing',   'IVP greater than (Writing)'),
            (12, 'ivp_long',      'IVP less than (Long)'),
            (13, 'ivhv_writing',  'IV-HV greater than (Writing)'),
            (14, 'ivhv_long',     'IV-HV less than (Long/Risky)'),
            (15, 'pcr_bearish',   'PCR Percentile above (Bearish reversal)'),
            (16, 'pcr_bullish',   'PCR Percentile below (Bullish reversal)'),
            (19, 'hc_llu',        'High Conviction L:LU threshold'),
            (20, 'hc_ssc',        'High Conviction S:SC threshold'),
            (21, 'sec_cycle1_days', 'Sector Cycle 1 lookback days'),
            (22, 'sec_cycle1_llu',  'Sector Cycle 1 L:LU threshold (Bullish)'),
            (23, 'sec_cycle1_ssc',  'Sector Cycle 1 S:SC threshold (Bearish)'),
            (24, 'sec_cycle2_days', 'Sector Cycle 2 lookback days'),
            (25, 'sec_cycle2_llu',  'Sector Cycle 2 L:LU threshold (Bullish)'),
            (26, 'sec_cycle2_ssc',  'Sector Cycle 2 S:SC threshold (Bearish)'),
            (27, 'hc_bull_thresh',  'Default entry without Sector Bullish'),
            (28, 'hc_bear_thresh',  'Default entry without Sector Bearish'),
            (29, 'hc_cycle_days',   'Cycle total for default entries'),
            (30, 'hcoi_prox_pct',   'Call difference Fut to HCOI (%)'),
            (31, 'hpoi_prox_pct',   'Put difference Fut to HPOI (%)'),
            (32, 'pcr_lookback',    'PCR Percentile lookback days'),
            (33, 'pcr_confirm_days', 'PCR Reversal confirmation days'),
        ]

        count = 0
        for row_idx, key, desc in mapping:
            if row_idx < len(rows) and len(rows[row_idx]) > 1:
                val_str = rows[row_idx][1].strip()
                if val_str:
                    try:
                        val = float(val_str.replace('%','').strip())
                        mc.execute(
                            "INSERT OR REPLACE INTO analytics_config (key, value, description, updated_at) VALUES (?, ?, ?, datetime('now'))",
                            (key, val, desc)
                        )
                        count += 1
                    except ValueError:
                        pass

        mc.commit()
        print(f"  {count} analytics parameters loaded")
    except Exception as e:
        print(f"  Analytics pull error: {e}")

def main():
    print(f"GSheet Pull — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}")
    tc = sqlite3.connect(TRADE_DB); mc = sqlite3.connect(MARKET_DB)
    try:
        pull_superset(tc); pull_accconfig(tc); pull_holidays(tc); pull_expiry(tc); pull_results(tc)
        pull_poip(mc); pull_iv(mc); pull_pcr(mc); pull_trigger(mc); pull_trap(mc)
        pull_bu_stk(mc); pull_bu_sector(mc)
        pull_sector_stock(mc); pull_index_stock(mc)
        pull_analytics(mc)
        pull_breadth(mc)
        print("Pull completed successfully")
    except Exception as e:
        import traceback; print(f"ERROR: {e}"); traceback.print_exc()
    finally:
        tc.close(); mc.close()

if __name__ == "__main__":
    main()
