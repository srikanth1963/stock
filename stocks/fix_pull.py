"""
Fixed pull functions for Holidays, POIP, BU_STK, BU_Sector
Run this on VM to patch the gsheet_pull.py issues
"""

import sqlite3
import csv
import io
import urllib.request
from datetime import datetime, date

SHEET_ID  = "1Kk41WTyE6s2lJO1WJwN0Sh7gEkDvxkAIP1pOswXNo8o"
TRADE_DB  = "/opt/smb-algo-stocks/trade.db"
MARKET_DB = "/opt/smb-algo-stocks/market_data.db"

def fetch_tab(tab_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={tab_name}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        content = resp.read().decode('utf-8')
    return list(csv.reader(io.StringIO(content)))

def parse_date(s):
    s = s.strip()
    for fmt in ('%d-%b-%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y-%m-%d',
                '%d/%m/%Y', '%d %b %Y', '%d %B %Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except:
            pass
    return None

def parse_float(s):
    try:
        return float(str(s).strip().replace('%', '').replace(',', '').replace(' ', ''))
    except:
        return None


def pull_holidays(tconn):
    """
    Holidays tab structure:
    Col A = Sr No, Col B = Date (15-Jan-2026), Col C = Day, Col D = Description
    """
    print("Pulling Holidays...")
    rows = fetch_tab("Holidays")
    if not rows:
        return

    tconn.execute("DELETE FROM holidays")
    count = 0
    for row in rows[1:]:  # skip header
        if not row or not row[1].strip():
            continue
        d = parse_date(row[1])  # Date is in column B (index 1)
        desc = row[3].strip() if len(row) > 3 else ''
        if d:
            tconn.execute(
                "INSERT OR IGNORE INTO holidays (holiday_date, description) VALUES (?, ?)",
                (d, desc)
            )
            count += 1

    tconn.commit()
    print(f"  {count} holidays loaded")


def pull_poip(mconn):
    """
    POIP tab structure:
    Col A-D = raw Quantsapp data (ignore)
    Col E = Symbol, Col F = Price Percentile, Col G = OI Percentile
    Row 1 = header (Symbol, Price Percentile, OI Percentile in E/F/G)
    """
    print("Pulling POIP...")
    rows = fetch_tab("POIP")
    if not rows:
        return

    today = date.today().strftime('%Y-%m-%d')
    count = 0
    for row in rows[1:]:  # skip header
        if len(row) < 7:
            continue
        ticker    = row[4].strip()  # Col E (index 4)
        price_pct = parse_float(row[5]) if len(row) > 5 else None  # Col F
        oi_pct    = parse_float(row[6]) if len(row) > 6 else None  # Col G

        if not ticker or price_pct is None:
            continue

        mconn.execute("""
            INSERT OR REPLACE INTO market_poip
            (date, nse_ticker, price_percentile, oi_percentile)
            VALUES (?, ?, ?, ?)
        """, (today, ticker, price_pct, oi_pct))
        count += 1

    # Purge records older than 10 days
    mconn.execute("DELETE FROM market_poip WHERE date < DATE('now', '-10 days')")
    mconn.commit()
    print(f"  {count} POIP records loaded")


def pull_bu_stk(mconn):
    """
    BU_STK tab structure (today's data — vertical format):
    Col A = Narration (L/S/LU/SC colored cell)
    Col B = Symbol
    Col C = Price
    Col D = OI
    Col E = Price %
    Col F = OI %
    Col H = Date (top right)
    """
    print("Pulling BU_STK...")
    rows = fetch_tab("BU_STK")
    if not rows or len(rows) < 2:
        return

    # Try to get date from col H row 1
    today = date.today().strftime('%Y-%m-%d')
    if rows[0] and len(rows[0]) > 7:
        d = parse_date(rows[0][7])
        if d:
            today = d

    count = 0
    valid_cls = {'L', 'S', 'LU', 'SC'}

    for row in rows[1:]:  # skip header
        if not row or not row[0].strip():
            continue
        cls    = row[0].strip().upper()
        ticker = row[1].strip() if len(row) > 1 else ''
        price  = parse_float(row[2]) if len(row) > 2 else None
        oi     = parse_float(row[3]) if len(row) > 3 else None
        price_chg = parse_float(row[4]) if len(row) > 4 else None
        oi_chg    = parse_float(row[5]) if len(row) > 5 else None

        if cls not in valid_cls or not ticker:
            continue

        mconn.execute("""
            INSERT OR REPLACE INTO market_oi_buildup
            (date, nse_ticker, classification, price_chg_pct, oi_chg_pct)
            VALUES (?, ?, ?, ?, ?)
        """, (today, ticker, cls, price_chg, oi_chg))
        count += 1

    mconn.execute("DELETE FROM market_oi_buildup WHERE date < DATE('now', '-30 days')")
    mconn.commit()
    print(f"  {count} Stock OI Buildup records loaded")


def pull_bu_sector(mconn):
    """
    BU_Sector tab structure (today's data — vertical grouped format):
    LONG header row
    SYMBOL | PRICE | OI header
    sector | price% | oi%
    ...
    SHORT header row
    SYMBOL | PRICE | OI header
    sector | price% | oi%
    ...
    LONG UNWINDING header row
    ...
    SHORT COVERING header row
    ...
    """
    print("Pulling BU_Sector...")
    rows = fetch_tab("BU_Sector")
    if not rows:
        return

    today = date.today().strftime('%Y-%m-%d')

    # Classification keywords
    cls_map = {
        'LONG UNWINDING': 'LU',
        'SHORT COVERING': 'SC',
        'LONG':           'L',
        'SHORT':          'S',
    }

    current_cls = None
    count = 0
    valid_cls = {'L', 'S', 'LU', 'SC'}

    for row in rows:
        if not row or not row[0].strip():
            continue

        cell = row[0].strip().upper()

        # Check if this is a classification header
        matched_cls = None
        # Check longer keys first to avoid 'LONG' matching 'LONG UNWINDING'
        for key in sorted(cls_map.keys(), key=len, reverse=True):
            if key in cell:
                matched_cls = cls_map[key]
                break

        if matched_cls:
            current_cls = matched_cls
            continue

        # Skip sub-header rows (SYMBOL, PRICE, OI)
        if cell in ('SYMBOL', 'NARRATION'):
            continue

        # Skip index entries (NIFTY, BANKNIFTY etc)
        if cell in ('NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'):
            continue

        if current_cls and current_cls in valid_cls:
            sector    = row[0].strip()
            price_chg = parse_float(row[1]) if len(row) > 1 else None
            oi_chg    = parse_float(row[2]) if len(row) > 2 else None

            if sector and sector.upper() not in ('SYMBOL', 'PRICE', 'OI'):
                mconn.execute("""
                    INSERT OR REPLACE INTO market_sector_buildup
                    (date, sector, classification, price_chg_pct, oi_chg_pct)
                    VALUES (?, ?, ?, ?, ?)
                """, (today, sector, current_cls, price_chg, oi_chg))
                count += 1

    mconn.execute("DELETE FROM market_sector_buildup WHERE date < DATE('now', '-30 days')")
    mconn.commit()
    print(f"  {count} Sector OI Buildup records loaded")


def main():
    print(f"\n{'='*50}")
    print(f"Fixing 4 tabs — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    tconn = sqlite3.connect(TRADE_DB)
    mconn = sqlite3.connect(MARKET_DB)

    # Add missing columns if needed
    try:
        mconn.execute("ALTER TABLE market_oi_buildup ADD COLUMN price_chg_pct REAL")
        mconn.execute("ALTER TABLE market_oi_buildup ADD COLUMN oi_chg_pct REAL")
        mconn.commit()
        print("Added price_chg_pct, oi_chg_pct columns to market_oi_buildup")
    except:
        pass  # Columns already exist

    try:
        mconn.execute("ALTER TABLE market_sector_buildup ADD COLUMN price_chg_pct REAL")
        mconn.execute("ALTER TABLE market_sector_buildup ADD COLUMN oi_chg_pct REAL")
        mconn.commit()
        print("Added price_chg_pct, oi_chg_pct columns to market_sector_buildup")
    except:
        pass

    try:
        pull_holidays(tconn)
        pull_poip(mconn)
        pull_bu_stk(mconn)
        pull_bu_sector(mconn)

        # Verify
        print("\n--- Verification ---")
        print(f"Holidays: {tconn.execute('SELECT COUNT(*) FROM holidays').fetchone()[0]}")
        print(f"POIP: {mconn.execute('SELECT COUNT(*) FROM market_poip').fetchone()[0]}")
        print(f"OI Buildup Stock: {mconn.execute('SELECT COUNT(*) FROM market_oi_buildup').fetchone()[0]}")
        print(f"OI Buildup Sector: {mconn.execute('SELECT COUNT(*) FROM market_sector_buildup').fetchone()[0]}")

        # Sample check
        print("\nSample POIP (first 3):")
        for r in mconn.execute("SELECT nse_ticker, price_percentile, oi_percentile FROM market_poip LIMIT 3"):
            print(f"  {r}")

        print("\nSample Sector (first 3):")
        for r in mconn.execute("SELECT date, sector, classification FROM market_sector_buildup LIMIT 3"):
            print(f"  {r}")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        tconn.close()
        mconn.close()

if __name__ == '__main__':
    main()
