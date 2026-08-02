"""
kotak_client.py

Thin wrapper around Kotak's official `neo_api_client` (Kotak-neo-api-v2 SDK)
for the execution-gateway VM. Mirrors the shape of your existing
breeze_client.py: login/session handling + order placement + status lookup.

Install: pip install --force-reinstall "git+https://github.com/Kotak-Neo/Kotak-neo-api-v2.git@v2.0.2#egg=neo_api_client"

VERIFY BEFORE LIVE USE:
- The exact login flow (totp_login + totp_validate) and place_order kwargs
  below are taken from Kotak's official v2 repo docs/issues, not from a
  live test against your account. Run one paper-mode order through this
  and inspect the raw response before trusting it in the retry/dedupe path.
- Session/token validity duration isn't documented publicly as far as I
  found — confirm whether it's daily (like Breeze) or longer, since that
  determines whether this needs a place in your morning routine.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import pyotp
from dotenv import load_dotenv
from neo_api_client import NeoAPI

load_dotenv(override=True)  # .env always wins, even over a stale manual export

logger = logging.getLogger("kotak_client")


@dataclass
class OrderResult:
    status: str            # "filled" | "rejected" | "error"
    order_id: Optional[str]
    raw_response: dict
    message: Optional[str] = None


class KotakClient:
    def __init__(self):
        self.consumer_key = os.environ["KOTAK_CONSUMER_KEY"]
        self.mobile_number = os.environ["KOTAK_MOBILE_NUMBER"]
        self.ucc = os.environ["KOTAK_UCC"]
        self.mpin = os.environ["KOTAK_MPIN"]
        self.totp_secret = os.environ["KOTAK_TOTP_SECRET"]  # from QR registration
        self.environment = os.environ.get("KOTAK_ENV", "prod")
        self._client: Optional[NeoAPI] = None

    def _current_totp(self) -> str:
        return pyotp.TOTP(self.totp_secret).now()

    def login(self) -> None:
        """Full 2FA login: totp_login (view token + session id) then
        totp_validate (trade token). Call once at startup and again if a
        call fails with an auth error."""
        client = NeoAPI(
            consumer_key=self.consumer_key,
            environment=self.environment,
        )
        client.totp_login(mobile_number=self.mobile_number, ucc=self.ucc, totp=self._current_totp())
        client.totp_validate(mpin=self.mpin)
        self._client = client
        logger.info("Kotak Neo session established")

    def _ensure_session(self) -> NeoAPI:
        if self._client is None:
            self.login()
        return self._client

    def place_order(
        self,
        trading_symbol: str,
        transaction_type: str,   # "B" or "S"
        quantity: int,
        order_type: str = "MKT",  # MKT | L | SL | SL-M
        product: str = "NRML",
        exchange_segment: str = "nse_fo",
        price: str = "0",
        trigger_price: str = "0",
    ) -> OrderResult:
        client = self._ensure_session()
        try:
            resp = client.place_order(
                exchange_segment=exchange_segment,
                product=product,
                price=price,
                order_type=order_type,
                quantity=str(quantity),
                validity="DAY",
                trading_symbol=trading_symbol,
                transaction_type=transaction_type,
                amo="NO",
                disclosed_quantity="0",
                market_protection="0",
                pf="N",
                trigger_price=trigger_price,
                tag=None,
            )
        except Exception as exc:
            logger.exception("Kotak place_order raised")
            return OrderResult(status="error", order_id=None, raw_response={}, message=str(exc))

        if resp.get("stat") == "Not_Ok":
            errs = resp.get("error", [])
            msg = errs[0]["message"] if errs else "unknown rejection"
            logger.error("Kotak order rejected: %s", msg)
            return OrderResult(status="rejected", order_id=None, raw_response=resp, message=msg)

        order_id = resp.get("nOrdNo") or resp.get("orderId") or resp.get("order_id")
        return OrderResult(status="filled", order_id=order_id, raw_response=resp)

    def order_status(self, order_id: str) -> dict:
        client = self._ensure_session()
        return client.order_history(order_id=order_id)
