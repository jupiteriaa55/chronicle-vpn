"""Background tasks: auto-revoke expired peers, expiry reminders."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot

from .db import Database
from .wireguard import WireGuardManager

log = logging.getLogger(__name__)


async def expiry_loop(
    db: Database, wg: WireGuardManager, bot: Bot, interval: int = 600
) -> None:
    """Every ``interval`` seconds: revoke peers of expired users; send T-1d reminder."""
    while True:
        try:
            await _tick(db, wg, bot)
        except Exception:
            log.exception("expiry tick failed")
        await asyncio.sleep(interval)


async def _tick(db: Database, wg: WireGuardManager, bot: Bot) -> None:
    now = dt.datetime.now(dt.UTC)
    users = await db.list_users()
    for u in users:
        if u.expires_at is None or u.is_blocked:
            continue
        active_peers = await db.list_peers(u.tg_id, only_active=True)
        if u.expires_at <= now and active_peers:
            await wg.revoke_user_peers(u.tg_id)
            try:
                await bot.send_message(
                    u.tg_id,
                    "⛔ Your VPN subscription expired and has been suspended.\n"
                    "Use /buy to renew — your peer keys will be reissued automatically.",
                )
            except Exception:
                pass
            continue
        # T-1d reminder window: between 23h and 24h before expiry
        delta = u.expires_at - now
        if active_peers and dt.timedelta(hours=23) < delta <= dt.timedelta(hours=24):
            try:
                await bot.send_message(
                    u.tg_id,
                    "⏳ Heads up — your VPN subscription expires in ~24h.\n"
                    "Tap /buy to extend now and avoid interruption.",
                )
            except Exception:
                pass
