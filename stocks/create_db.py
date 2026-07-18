import sqlite3

conn = sqlite3.connect('/opt/smb-algo-stocks/trade.db')
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS stock_master (
    id INTEGER PRIMARY KEY,
    nse_ticker TEXT NOT NULL UNIQUE,
    breeze_code TEXT NOT NULL,
    lot_size INTEGER NOT NULL,
    company_name TEXT,
    is_active INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

c.execute("""CREATE TABLE IF NOT EXISTS account_config (
    id INTEGER PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT,
    dp_name TEXT,
    capital_allocation REAL,
    max_daily_loss REAL,
    lots_per_trade INTEGER DEFAULT 1,
    order_price_type TEXT DEFAULT 'aggressive',
    status TEXT DEFAULT 'Active',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

c.execute("""CREATE TABLE IF NOT EXISTS account_stocks (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    nse_ticker TEXT NOT NULL,
    UNIQUE(account_id, nse_ticker)
)""")

c.execute("""CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    nse_ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_price REAL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, nse_ticker)
)""")

c.execute("""CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    trade_date DATE NOT NULL,
    nse_ticker TEXT NOT NULL,
    breeze_code TEXT NOT NULL,
    expiry_date DATE NOT NULL,
    direction TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike_price REAL NOT NULL,
    lots INTEGER NOT NULL,
    lot_size INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL,
    entry_time TIMESTAMP,
    exit_price REAL,
    exit_time TIMESTAMP,
    exit_reason TEXT,
    pnl REAL,
    status TEXT DEFAULT 'OPEN',
    order_id TEXT,
    current_ltp REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

c.execute("""CREATE TABLE IF NOT EXISTS daily_pnl (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    date DATE NOT NULL,
    realised_pnl REAL DEFAULT 0,
    unrealised_pnl REAL DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    current_spot REAL,
    loss_limit_breached INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, date)
)""")

c.execute("""CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY,
    holiday_date DATE NOT NULL UNIQUE,
    description TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS expiry_calendar (
    id INTEGER PRIMARY KEY,
    expiry_date DATE NOT NULL,
    expiry_type TEXT NOT NULL,
    underlying TEXT NOT NULL,
    UNIQUE(expiry_date, underlying)
)""")

c.execute("""CREATE TABLE IF NOT EXISTS results_calendar (
    id INTEGER PRIMARY KEY,
    nse_ticker TEXT NOT NULL,
    result_date DATE NOT NULL,
    UNIQUE(nse_ticker, result_date)
)""")

conn.commit()
conn.close()
print('trade.db created successfully with all 9 tables')
