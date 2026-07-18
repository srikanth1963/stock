"""
database.py — SQLAlchemy ORM models for SMB Algo Stocks
"""
from sqlalchemy import create_engine, Column, Integer, Float, String, Date, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

TRADE_DB_URL  = "sqlite:////opt/smb-algo-stocks/trade.db"
MARKET_DB_URL = "sqlite:////opt/smb-algo-stocks/market_data.db"

trade_engine  = create_engine(TRADE_DB_URL,  connect_args={"check_same_thread": False})
market_engine = create_engine(MARKET_DB_URL, connect_args={"check_same_thread": False})

TradeBase  = declarative_base()
MarketBase = declarative_base()

TradeSession  = sessionmaker(bind=trade_engine)
MarketSession = sessionmaker(bind=market_engine)


# ── TRADE DB MODELS ──────────────────────────────────────────────────────────

class StockMaster(TradeBase):
    __tablename__ = "stock_master"
    id          = Column(Integer, primary_key=True)
    nse_ticker  = Column(String, unique=True, nullable=False)
    breeze_code = Column(String, nullable=False)
    lot_size    = Column(Integer, nullable=False)
    company_name= Column(String)
    is_active   = Column(Integer, default=0)
    updated_at  = Column(DateTime, default=datetime.utcnow)


class AccountConfig(TradeBase):
    __tablename__ = "account_config"
    id                  = Column(Integer, primary_key=True)
    account_name        = Column(String, nullable=False)
    account_type        = Column(String)
    dp_name             = Column(String)
    capital_allocation  = Column(Float)
    max_daily_loss      = Column(Float)
    lots_per_trade      = Column(Integer, default=1)
    order_price_type    = Column(String, default="aggressive")
    status              = Column(String, default="Active")
    paper_trading       = Column(Integer, default=1)
    updated_at          = Column(DateTime, default=datetime.utcnow)


class AccountStocks(TradeBase):
    __tablename__ = "account_stocks"
    id          = Column(Integer, primary_key=True)
    account_id  = Column(Integer, nullable=False)
    nse_ticker  = Column(String, nullable=False)


class Signal(TradeBase):
    __tablename__ = "signals"
    id          = Column(Integer, primary_key=True)
    nse_ticker  = Column(String, nullable=False)
    direction   = Column(String, nullable=False)   # BUY / SELL
    signal_price= Column(Float)
    received_at = Column(DateTime, default=datetime.utcnow)


class Trade(TradeBase):
    __tablename__ = "trades"
    id            = Column(Integer, primary_key=True)
    account_id    = Column(Integer, nullable=False)
    trade_date    = Column(Date, nullable=False)
    nse_ticker    = Column(String, nullable=False)
    breeze_code   = Column(String, nullable=False)
    expiry_date   = Column(Date, nullable=False)
    direction     = Column(String, nullable=False)
    option_type   = Column(String, nullable=False)  # CE / PE
    strike_price  = Column(Float, nullable=False)
    lots          = Column(Integer, nullable=False)
    lot_size      = Column(Integer, nullable=False)
    quantity      = Column(Integer, nullable=False)
    entry_price   = Column(Float)
    entry_time    = Column(DateTime)
    exit_price    = Column(Float)
    exit_time     = Column(DateTime)
    exit_reason   = Column(String)
    pnl           = Column(Float)
    status        = Column(String, default="OPEN")
    order_id      = Column(String)
    current_ltp   = Column(Float)
    created_at    = Column(DateTime, default=datetime.utcnow)


class DailyPnL(TradeBase):
    __tablename__ = "daily_pnl"
    id                   = Column(Integer, primary_key=True)
    account_id           = Column(Integer, nullable=False)
    date                 = Column(Date, nullable=False)
    realised_pnl         = Column(Float, default=0)
    unrealised_pnl       = Column(Float, default=0)
    total_trades         = Column(Integer, default=0)
    current_spot         = Column(Float)
    loss_limit_breached  = Column(Integer, default=0)
    updated_at           = Column(DateTime, default=datetime.utcnow)


class Holiday(TradeBase):
    __tablename__ = "holidays"
    id           = Column(Integer, primary_key=True)
    holiday_date = Column(Date, unique=True, nullable=False)
    description  = Column(String)


class ExpiryCalendar(TradeBase):
    __tablename__ = "expiry_calendar"
    id          = Column(Integer, primary_key=True)
    expiry_date = Column(Date, nullable=False)
    expiry_type = Column(String, nullable=False)
    underlying  = Column(String, nullable=False)


class ResultsCalendar(TradeBase):
    __tablename__ = "results_calendar"
    id          = Column(Integer, primary_key=True)
    nse_ticker  = Column(String, nullable=False)
    result_date = Column(Date, nullable=False)


# ── MARKET DB MODELS ─────────────────────────────────────────────────────────

class MarketPOIP(MarketBase):
    __tablename__ = "market_poip"
    id               = Column(Integer, primary_key=True)
    date             = Column(Date, nullable=False)
    nse_ticker       = Column(String, nullable=False)
    price_percentile = Column(Float)
    oi_percentile    = Column(Float)
    created_at       = Column(DateTime, default=datetime.utcnow)


class MarketIV(MarketBase):
    __tablename__ = "market_iv"
    id         = Column(Integer, primary_key=True)
    date       = Column(Date, nullable=False)
    nse_ticker = Column(String, nullable=False)
    price      = Column(Float)
    iv         = Column(Float)
    hv         = Column(Float)
    ivr        = Column(Float)
    ivp        = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class MarketOIBuildup(MarketBase):
    __tablename__ = "market_oi_buildup"
    id             = Column(Integer, primary_key=True)
    date           = Column(Date, nullable=False)
    nse_ticker     = Column(String, nullable=False)
    classification = Column(String, nullable=False)
    price_chg_pct  = Column(Float)
    oi_chg_pct     = Column(Float)
    created_at     = Column(DateTime, default=datetime.utcnow)


class MarketSectorBuildup(MarketBase):
    __tablename__ = "market_sector_buildup"
    id             = Column(Integer, primary_key=True)
    date           = Column(Date, nullable=False)
    sector         = Column(String, nullable=False)
    classification = Column(String, nullable=False)
    price_chg_pct  = Column(Float)
    oi_chg_pct     = Column(Float)
    created_at     = Column(DateTime, default=datetime.utcnow)


class MarketOITrigger(MarketBase):
    __tablename__ = "market_oi_trigger"
    id              = Column(Integer, primary_key=True)
    date            = Column(Date, nullable=False)
    nse_ticker      = Column(String, nullable=False)
    futures_price   = Column(Float)
    call_strike     = Column(Float)
    call_oi         = Column(Float)
    call_chg_oi_pct = Column(Float)
    call_diff_pct   = Column(Float)
    put_strike      = Column(Float)
    put_oi          = Column(Float)
    put_chg_oi_pct  = Column(Float)
    put_diff_pct    = Column(Float)
    updated_at      = Column(DateTime, default=datetime.utcnow)


class MarketWritersTrap(MarketBase):
    __tablename__ = "market_writers_trap"
    id           = Column(Integer, primary_key=True)
    date         = Column(Date, nullable=False)
    nse_ticker   = Column(String, nullable=False)
    signal_type  = Column(String, nullable=False)
    signal_price = Column(Float)
    signal_date  = Column(Date)
    close_price  = Column(Float)
    return_pct   = Column(Float)
    updated_at   = Column(DateTime, default=datetime.utcnow)


def get_trade_db():
    db = TradeSession()
    try:
        yield db
    finally:
        db.close()


def get_market_db():
    db = MarketSession()
    try:
        yield db
    finally:
        db.close()
