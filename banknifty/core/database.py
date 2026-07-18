"""
SMB Algo — Database Schema
SQLite via SQLAlchemy. Single file, zero config, easy to backup.
Tables: signal_state, trades, daily_pnl
"""

import logging
from datetime import date, datetime
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Boolean, Date, DateTime, Text, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "smb_algo.db"
DB_PATH.parent.mkdir(exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False}
)

# Enable WAL mode for better concurrent read performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────

class SignalState(Base):
    """
    Persists the last known UT Bot signal direction.
    Used for morning carry-over logic.
    One row per strategy — updated on every signal change.
    """
    __tablename__ = "signal_state"

    id              = Column(Integer, primary_key=True)
    strategy_id     = Column(String(20), unique=True, nullable=False)  # e.g. "utlrg"
    signal          = Column(String(4), nullable=False)                 # "BUY" or "SELL"
    signal_date     = Column(Date, nullable=False)
    signal_time     = Column(DateTime, nullable=False)
    candle_close    = Column(DateTime, nullable=True)   # candle that generated the signal
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Trade(Base):
    """
    Complete record of every trade — paper and live.
    One row per trade (entry → exit).
    """
    __tablename__ = "trades"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    trade_date      = Column(Date, nullable=False, index=True)
    account_name    = Column(String(50), nullable=False, index=True)
    strategy_id     = Column(String(20), nullable=False)
    paper_mode      = Column(Boolean, nullable=False, default=True)

    # Signal
    signal          = Column(String(4), nullable=False)    # BUY or SELL
    signal_time     = Column(DateTime, nullable=False)

    # Option details
    instrument      = Column(String(20), nullable=False)   # NIFTY
    strike          = Column(Integer, nullable=False)
    option_type     = Column(String(2), nullable=False)    # CE or PE
    expiry_date     = Column(Date, nullable=False)
    quantity_lots   = Column(Integer, nullable=False)
    lot_size        = Column(Integer, nullable=False)
    total_quantity  = Column(Integer, nullable=False)      # lots * lot_size

    # Entry
    entry_time      = Column(DateTime, nullable=True)
    entry_price     = Column(Float, nullable=True)
    entry_order_id  = Column(String(50), nullable=True)
    entry_spot      = Column(Float, nullable=True)         # spot price at entry

    # Exit
    exit_time       = Column(DateTime, nullable=True)
    exit_price      = Column(Float, nullable=True)
    exit_order_id   = Column(String(50), nullable=True)
    exit_reason     = Column(String(30), nullable=True)    # REVERSE_SIGNAL / EOD / LOSS_LIMIT / KILL

    # P&L
    pnl             = Column(Float, nullable=True)
    preclosure_done = Column(Boolean, default=False)
    remaining_lots  = Column(Integer, nullable=True)
    current_ltp     = Column(Float, nullable=True)         # (exit - entry) * total_quantity
    pnl_pct         = Column(Float, nullable=True)         # pnl / (entry * total_quantity) * 100

    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DailyPnL(Base):
    """
    Daily P&L summary per account.
    Updated in real-time. Used for loss limit checks.
    """
    __tablename__ = "daily_pnl"

    id              = Column(Integer, primary_key=True)
    pnl_date        = Column(Date, nullable=False, index=True)
    account_name    = Column(String(50), nullable=False)
    strategy_id     = Column(String(20), nullable=False)

    realised_pnl    = Column(Float, default=0.0)   # sum of closed trade P&Ls
    mtm_pnl         = Column(Float, default=0.0)   # open position unrealised P&L
    combined_pnl    = Column(Float, default=0.0)   # realised + mtm

    trade_count     = Column(Integer, default=0)
    trading_halted  = Column(Boolean, default=False)
    current_spot    = Column(Float, nullable=True)  # True if loss limit breached
    halt_reason     = Column(String(50), nullable=True)

    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookLog(Base):
    """
    Raw log of every webhook received. Useful for debugging.
    """
    __tablename__ = "webhook_log"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    received_at     = Column(DateTime, default=datetime.utcnow, index=True)
    strategy_id     = Column(String(20), nullable=False)
    raw_payload     = Column(Text, nullable=False)
    signal          = Column(String(4), nullable=True)
    processed       = Column(Boolean, default=False)
    error           = Column(Text, nullable=True)


# ── Session helper ────────────────────────────────────────────────────────────

@contextmanager
def get_db() -> Session:
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"✓ Database created at {DB_PATH}")

    # Verify all tables exist
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"✓ Tables: {', '.join(tables)}")
