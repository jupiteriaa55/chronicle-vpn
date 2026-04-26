"""YooKassa (RUB) payment provider via the official ``yookassa`` SDK."""
from __future__ import annotations

import logging
from uuid import uuid4

from yookassa import Configuration
from yookassa import Payment as YPayment

from ..config import Settings
from ..db import Database
from .base import PaymentInvoice

log = logging.getLogger(__name__)
PROVIDER_NAME = "yookassa"


class YooKassaProvider:
    name: str = PROVIDER_NAME

    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        if settings.yookassa_enabled:
            Configuration.account_id = settings.yookassa_shop_id
            Configuration.secret_key = settings.yookassa_secret_key

    @property
    def enabled(self) -> bool:
        return self.settings.yookassa_enabled

    async def create_invoice(self, tg_id: int) -> PaymentInvoice:
        if not self.enabled:
            raise RuntimeError("YooKassa is not configured")
        s = self.settings
        amount = f"{s.subscription_price_rub:.2f}"
        idemp = uuid4().hex
        description = f"VPN subscription, {s.subscription_days} days (tg:{tg_id})"
        payload: dict[str, object] = {
            "amount": {"value": amount, "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": s.yookassa_return_url},
            "capture": True,
            "description": description,
            "metadata": {"tg_id": str(tg_id)},
        }
        # SDK call is sync; safe to call directly (small request).
        y = YPayment.create(payload, idemp)
        external_id = y.id
        pay_url = y.confirmation.confirmation_url if y.confirmation else None

        payment_id = await self.db.create_payment(
            tg_id=tg_id,
            provider=PROVIDER_NAME,
            amount=float(s.subscription_price_rub),
            currency="RUB",
            days_added=s.subscription_days,
            external_id=external_id,
        )
        log.info("YooKassa invoice created: db=%s ext=%s", payment_id, external_id)
        return PaymentInvoice(
            payment_id=payment_id,
            external_id=external_id,
            pay_url=pay_url,
            description=description,
            amount=float(s.subscription_price_rub),
            currency="RUB",
            days=s.subscription_days,
        )
