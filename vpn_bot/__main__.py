"""Entry point: ``python -m vpn_bot`` runs the bot + webhook server."""
from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_settings
from .db import Database
from .handlers import admin_router, payments_router, user_router
from .payments.cryptobot import CryptoBotProvider
from .payments.stars import StarsProvider
from .payments.yookassa import YooKassaProvider
from .scheduler import expiry_loop
from .webhook import build_app
from .wireguard import WireGuardManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
log = logging.getLogger("vpn_bot")


async def amain() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    await db.connect()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    wg = WireGuardManager(settings, db)
    stars = StarsProvider(settings, db)
    yookassa = YooKassaProvider(settings, db)
    cryptobot = CryptoBotProvider(settings, db)

    dp = Dispatcher()
    dp["settings"] = settings
    dp["db"] = db
    dp["wg"] = wg
    dp["stars"] = stars
    dp["yookassa"] = yookassa
    dp["cryptobot"] = cryptobot

    dp.include_router(user_router)
    dp.include_router(payments_router)
    dp.include_router(admin_router)

    # Webhook server (YooKassa + CryptoBot callbacks)
    app = build_app(settings=settings, db=db, wg=wg, bot=bot)
    config = uvicorn.Config(
        app, host=settings.webhook_host, port=settings.webhook_port, log_level="info"
    )
    server = uvicorn.Server(config)

    log.info("Starting webhook server on %s:%s", settings.webhook_host, settings.webhook_port)
    log.info("Starting Telegram bot polling…")
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve(),
        expiry_loop(db, wg, bot),
    )


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
