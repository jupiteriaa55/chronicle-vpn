"""Common payment-provider interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class PaymentInvoice:
    """Returned by ``PaymentProvider.create_invoice``."""

    payment_id: int           # internal db id
    external_id: str | None   # provider id (e.g. yookassa payment uuid)
    pay_url: str | None       # checkout url (or telegram://invoice for Stars)
    description: str
    amount: float
    currency: str
    days: int


@dataclass(slots=True)
class PaymentResult:
    """Yielded by webhook/handler when a payment status update arrives."""

    payment_id: int
    tg_id: int
    status: str               # 'paid' | 'failed' | 'refunded'
    days: int


class PaymentProvider(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    async def create_invoice(self, tg_id: int) -> PaymentInvoice: ...
