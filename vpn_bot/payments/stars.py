"""Telegram Stars (XTR) provider.

Stars payments are issued as native Telegram invoices with currency ``XTR``.
The bot doesn't need any external creds; only the bot token. The flow:

1. ``create_invoice`` creates an internal ``payments`` row (status=pending) and
   returns an invoice payload which the handler turns into ``send_invoice``.
2. ``aiogram`` ``pre_checkout_query`` is auto-approved.
3. ``successful_payment`` calls :func:`mark_paid` in ``handlers``.
"""
from __future__ import annotations

from ..config import Settings
from ..db import Database
from .base import PaymentInvoice

PROVIDER_NAME = "stars"


class StarsProvider:
    name: str = PROVIDER_NAME

    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

    @property
    def enabled(self) -> bool:
        return True  # always available; needs only bot token

    async def create_invoice(self, tg_id: int) -> PaymentInvoice:
        s = self.settings
        payment_id = await self.db.create_payment(
            tg_id=tg_id,
            provider=PROVIDER_NAME,
            amount=float(s.subscription_price_stars),
            currency="XTR",
            days_added=s.subscription_days,
        )
        return PaymentInvoice(
            payment_id=payment_id,
            external_id=None,
            pay_url=None,
            description=f"VPN subscription, {s.subscription_days} days",
            amount=float(s.subscription_price_stars),
            currency="XTR",
            days=s.subscription_days,
        )
