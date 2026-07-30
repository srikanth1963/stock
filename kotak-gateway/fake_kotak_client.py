"""
fake_kotak_client.py

Stand-in for kotak_client.py used ONLY for local testing on your laptop.
Returns made-up but realistic responses instead of calling Kotak's real
API — so you can test the gateway's dedup/guard logic safely, with no
real account, no real credentials, no real orders.

HOW TO USE:
1. Put this file in the same kotak-gateway/ folder as the other two.
2. Open kotak_execute_service.py, find this line near the top:
       from kotak_client import KotakClient
   Temporarily change it to:
       from fake_kotak_client import FakeKotakClient as KotakClient
3. Run the service (see run instructions at the bottom of this file).
4. When you're ready to test against the real Kotak API later, change
   that import line back.
"""

import itertools
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderResult:
    status: str
    order_id: Optional[str]
    raw_response: dict
    message: Optional[str] = None


class FakeKotakClient:
    _counter = itertools.count(1)

    def __init__(self):
        print("[FakeKotakClient] initialized — no real API calls will be made")

    def login(self):
        print("[FakeKotakClient] pretend login successful")

    def place_order(self, trading_symbol, transaction_type, quantity, **kwargs):
        order_id = f"FAKE{next(self._counter):04d}"
        print(f"[FakeKotakClient] pretend order placed: {trading_symbol} "
              f"{transaction_type} qty={quantity} -> order_id={order_id}")
        return OrderResult(
            status="filled",
            order_id=order_id,
            raw_response={"stat": "Ok", "price": "412.35", "order_id": order_id},
        )

    def order_status(self, order_id):
        return {"order_id": order_id, "status": "filled"}


# ---------------------------------------------------------------------------
# HOW TO RUN THE WHOLE THING LOCALLY (after step 2 above):
#
#   pip install fastapi uvicorn pyotp
#   uvicorn kotak_execute_service:app --reload --port 8010
#
# Then in a SECOND terminal window, test it with:
#
#   curl -X POST http://localhost:8010/execute -H "Content-Type: application/json" -d "{\"action\":\"entry\",\"symbol\":\"BANKNIFTY\",\"side\":\"BUY\",\"qty_lots\":2,\"signal_id\":\"test-entry-1\"}"
#
# You should see a JSON response with status "filled" and a fake order_id.
# Copy that order_id, then test an exit:
#
#   curl -X POST http://localhost:8010/execute -H "Content-Type: application/json" -d "{\"action\":\"exit\",\"symbol\":\"BANKNIFTY\",\"side\":\"SELL\",\"qty_lots\":2,\"signal_id\":\"test-exit-1\",\"exit_order_id\":\"PASTE_ORDER_ID_HERE\"}"
#
# Then test the safety guard by trying to exit an order_id that was never
# opened — it should return an error (409), not silently succeed:
#
#   curl -X POST http://localhost:8010/execute -H "Content-Type: application/json" -d "{\"action\":\"exit\",\"symbol\":\"BANKNIFTY\",\"side\":\"SELL\",\"qty_lots\":2,\"signal_id\":\"test-exit-bad\",\"exit_order_id\":\"NOTREAL\"}"
# ---------------------------------------------------------------------------
