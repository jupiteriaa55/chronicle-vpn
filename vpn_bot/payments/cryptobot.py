"""CryptoBot (Crypto Pay API) provider — accepts USDT/TON/BTC etc.

Docs: https://help.crypt.bot/crypto-pay-api
"""
from __future__ import annotations

import logging

import httpx

from ..config import Settings
from ..db import Database
from .base import PaymentInvoice

log = logging.getLogger(__name__)
PROVIDER_NAME = "cryptobot"


class CryptoBotProvider:
    name: str = PROVIDER_NAME

    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        host = "testnet-pay.crypt.bot" if settings.cryptobot_testnet else "pay.crypt.bot"
        self.api_base = f"https://{host}/api"
        self._client = httpx.AsyncClient(
            timeout=20.0,
            headers={"Crypto-Pay-API-Token": settings.cryptobot_token or ""},
        )

    @property
    def enabled(self) -> bool:
        return self.settings.cryptobot_enabled

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_invoice(self, tg_id: int) -> PaymentInvoice:
        if not self.enabled:
            raise RuntimeError("CryptoBot is not configured")
        s = self.settings
        amount = f"{s.subscription_price_usd:.2f}"
        description = f"VPN subscription, {s.subscription_days} days"
        payload: dict[str, object] = {
            "asset": "USDT",
            "amount": amount,
            "description": description,
            "payload": str(tg_id),
            "allow_anonymous": False,
        }
        resp = await self._client.post(f"{self.api_base}/createInvoice", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"CryptoBot error: {data}")
        inv = data["result"]
        external_id = str(inv["invoice_id"])
        pay_url = inv.get("pay_url") or inv.get("bot_invoice_url") or inv.get("mini_app_invoice_url")

        payment_id = await self.db.create_payment(
            tg_id=tg_id,
            provider=PROVIDER_NAME,
            amount=float(amount),
            currency="USDT",
            days_added=s.subscription_days,
            external_id=external_id,
        )
        log.info("CryptoBot invoice created: db=%s ext=%s", payment_id, external_id)
        return PaymentInvoice(
            payment_id=payment_id,
            external_id=external_id,
            pay_url=pay_url,
            description=description,
            amount=float(amount),
            currency="USDT",
            days=s.subscription_days,
        )
