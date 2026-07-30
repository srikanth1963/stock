"""
kotak_execute_service.py

Runs on the Kotak VM. Receives execution payloads from Primary VM and
places/exits orders via kotak_client.py. Deliberately thin: no scheduler,
no Day Bias, no MTM — Primary owns all trading decisions and state.

Two safety mechanisms, per the design we agreed on:
1. signal_id dedup — a retried POST from Primary never double-places an order.
2. Local open-position guard — before executing an exit, confirm the
   order_id was actually opened here. Rejects exits against unknown
   positions instead of blindly forwarding them to Kotak.

State is a single SQLite file, wiped/rebuilt only by what Primary tells
it — this is a guard, not a second source of truth.
"""

import sqlite3
import logging
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fake_kotak_client import FakeKotakClient as KotakClient

logger = logging.getLogger("kotak_execute_service")
app = FastAPI()
kotak = KotakClient()

DB_PATH = "/opt/kotak-gateway/gateway.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                status TEXT,
                order_id TEXT,
                response_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS open_positions (
                order_id TEXT PRIMARY KEY,
                symbol TEXT,
                qty_lots INTEGER
            )
        """)


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class ExecutePayload(BaseModel):
    action: str          # entry | exit | partial_exit
    symbol: str
    side: str             # BUY | SELL
    qty_lots: int
    order_type: str = "MARKET"
    signal_id: str
    reason: str = ""
    lot_size: int = 1     # multiplied with qty_lots for actual quantity
    exit_order_id: str | None = None  # required for exit/partial_exit


def _to_kotak_txn_type(side: str) -> str:
    return "B" if side.upper() == "BUY" else "S"


@app.on_event("startup")
def _startup():
    init_db()
    kotak.login()


@app.post("/execute")
def execute(payload: ExecutePayload):
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM signals WHERE signal_id = ?", (payload.signal_id,)
        ).fetchone()
        if existing:
            logger.info("Duplicate signal_id %s — returning cached result", payload.signal_id)
            return {
                "status": existing["status"],
                "order_id": existing["order_id"],
                "note": "duplicate_signal_id_returned_cached_result",
            }

        if payload.action in ("exit", "partial_exit"):
            if not payload.exit_order_id:
                raise HTTPException(400, "exit_order_id required for exit/partial_exit")
            pos = conn.execute(
                "SELECT * FROM open_positions WHERE order_id = ?", (payload.exit_order_id,)
            ).fetchone()
            if not pos:
                # Loud rejection, not a silent forward to Kotak's API.
                raise HTTPException(
                    409,
                    f"No local record of open position {payload.exit_order_id} — refusing exit",
                )

        qty = payload.qty_lots * payload.lot_size
        result = kotak.place_order(
            trading_symbol=payload.symbol,
            transaction_type=_to_kotak_txn_type(payload.side),
            quantity=qty,
            order_type="MKT" if payload.order_type == "MARKET" else payload.order_type,
        )

        conn.execute(
            "INSERT INTO signals (signal_id, status, order_id, response_json) VALUES (?, ?, ?, ?)",
            (payload.signal_id, result.status, result.order_id, str(result.raw_response)),
        )

        if result.status == "filled":
            if payload.action == "entry":
                conn.execute(
                    "INSERT OR REPLACE INTO open_positions (order_id, symbol, qty_lots) VALUES (?, ?, ?)",
                    (result.order_id, payload.symbol, payload.qty_lots),
                )
            elif payload.action == "exit":
                conn.execute(
                    "DELETE FROM open_positions WHERE order_id = ?", (payload.exit_order_id,)
                )
            elif payload.action == "partial_exit":
                conn.execute(
                    "UPDATE open_positions SET qty_lots = qty_lots - ? WHERE order_id = ?",
                    (payload.qty_lots, payload.exit_order_id),
                )

        if result.status != "filled":
            raise HTTPException(502, detail={"status": result.status, "message": result.message})

        return {
            "status": result.status,
            "order_id": result.order_id,
            "fill_price": result.raw_response.get("price"),
            "filled_qty_lots": payload.qty_lots,
        }


@app.get("/health")
def health():
    return {"status": "ok"}
