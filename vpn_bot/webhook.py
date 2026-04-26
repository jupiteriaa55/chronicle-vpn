"""FastAPI app exposing webhook endpoints for YooKassa + CryptoBot.

Run alongside the bot polling loop on the same VPS.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .db import Database
from .wireguard import WireGuardManager

log = logging.getLogger(__name__)


def build_app(
    *, settings: Settings, db: Database, wg: WireGuardManager, bot: Bot
) -> FastAPI:
    app = FastAPI(title="chronicle-vpn webhooks")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/yookassa")
    async def yookassa_webhook(request: Request) -> dict[str, Any]:
        # YooKassa pushes JSON; we just look up by external_id and finalize.
        data = await request.json()
        if data.get("event") != "payment.succeeded":
            return {"status": "ignored"}
        obj = data.get("object", {})
        external_id = obj.get("id")
        if not external_id:
            raise HTTPException(400, "missing payment id")
        payment = await db.get_payment_by_external("yookassa", external_id)
        if payment is None:
            raise HTTPException(404, "unknown payment")
        if payment.status == "paid":
            return {"status": "already paid"}
        await db.mark_payment_paid(payment.id, external_id=external_id)
        user = await db.extend_subscription(payment.tg_id, payment.days_added)
        if not await db.list_peers(payment.tg_id, only_active=True):
            await wg.create_peer(payment.tg_id, name="default")
        try:
            await bot.send_message(
                payment.tg_id,
                "✅ YooKassa payment received — "
                f"<b>{payment.days_added} day(s)</b> added.\n"
                f"Active until <b>{user.expires_at:%Y-%m-%d %H:%M UTC}</b>. "
                "Tap 📥 Get config in /start to download your file.",
            )
        except Exception:
            log.exception("notify user failed")
        return {"status": "ok"}

    @app.post("/webhook/cryptobot")
    async def cryptobot_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        sig = request.headers.get("crypto-pay-api-signature", "")
        if settings.cryptobot_token:
            secret = hashlib.sha256(settings.cryptobot_token.encode()).digest()
            expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                raise HTTPException(401, "bad signature")
        data = await request.json()
        if data.get("update_type") != "invoice_paid":
            return {"status": "ignored"}
        payload = data.get("payload", {})
        external_id = str(payload.get("invoice_id"))
        payment = await db.get_payment_by_external("cryptobot", external_id)
        if payment is None:
            raise HTTPException(404, "unknown invoice")
        if payment.status == "paid":
            return {"status": "already paid"}
        await db.mark_payment_paid(payment.id, external_id=external_id)
        user = await db.extend_subscription(payment.tg_id, payment.days_added)
        if not await db.list_peers(payment.tg_id, only_active=True):
            await wg.create_peer(payment.tg_id, name="default")
        try:
            await bot.send_message(
                payment.tg_id,
                "✅ Crypto payment received — "
                f"<b>{payment.days_added} day(s)</b> added.\n"
                f"Active until <b>{user.expires_at:%Y-%m-%d %H:%M UTC}</b>.",
            )
        except Exception:
            log.exception("notify user failed")
        return {"status": "ok"}

    return app
