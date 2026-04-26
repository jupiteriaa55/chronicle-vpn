"""Payment flow: /buy, provider chooser, Stars invoice + webhook handlers."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from ..config import Settings
from ..db import Database
from ..payments.cryptobot import CryptoBotProvider
from ..payments.stars import StarsProvider
from ..payments.yookassa import YooKassaProvider
from ..wireguard import WireGuardManager

log = logging.getLogger(__name__)
router = Router(name="payments")


def _provider_kb(settings: Settings, yk: YooKassaProvider, cb: CryptoBotProvider) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                text=f"⭐ Stars · {settings.subscription_price_stars}",
                callback_data="pay:stars",
            )
        ]
    )
    if yk.enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💳 YooKassa · {settings.subscription_price_rub}₽",
                    callback_data="pay:yookassa",
                )
            ]
        )
    if cb.enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🪙 Crypto · {settings.subscription_price_usd}$",
                    callback_data="pay:cryptobot",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« Back", callback_data="profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("buy"))
async def cmd_buy(
    msg: Message,
    settings: Settings,
    yookassa: YooKassaProvider,
    cryptobot: CryptoBotProvider,
) -> None:
    await msg.answer(
        f"<b>Subscription · {settings.subscription_days} days</b>\n\n"
        "Choose how to pay:",
        reply_markup=_provider_kb(settings, yookassa, cryptobot),
    )


@router.callback_query(F.data == "buy")
async def cb_buy(
    cb: CallbackQuery,
    settings: Settings,
    yookassa: YooKassaProvider,
    cryptobot: CryptoBotProvider,
) -> None:
    await cb.answer()
    if not isinstance(cb.message, Message):
        return
    await cb.message.edit_text(
        f"<b>Subscription · {settings.subscription_days} days</b>\n\nChoose how to pay:",
        reply_markup=_provider_kb(settings, yookassa, cryptobot),
    )


# ---------- Telegram Stars (XTR native invoice) ----------
@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(
    cb: CallbackQuery, bot: Bot, db: Database, stars: StarsProvider
) -> None:
    await cb.answer()
    if cb.message is None or cb.from_user is None:
        return
    invoice = await stars.create_invoice(cb.from_user.id)
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title="VPN Subscription",
        description=invoice.description,
        payload=f"stars:{invoice.payment_id}",
        currency="XTR",
        prices=[LabeledPrice(label="Subscription", amount=int(invoice.amount))],
        provider_token="",  # Stars use empty provider_token
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot) -> None:
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment(
    msg: Message,
    db: Database,
    wg: WireGuardManager,
    settings: Settings,
) -> None:
    sp = msg.successful_payment
    if sp is None or msg.from_user is None:
        return
    payload = sp.invoice_payload  # 'stars:<payment_id>'
    try:
        _provider, pid = payload.split(":")
        payment_id = int(pid)
    except Exception:
        log.error("Bad invoice_payload: %s", payload)
        return
    payment = await db.get_payment(payment_id)
    if payment is None or payment.status == "paid":
        return
    await db.mark_payment_paid(
        payment_id, external_id=sp.telegram_payment_charge_id
    )
    user = await db.extend_subscription(payment.tg_id, payment.days_added)
    await msg.answer(
        f"✅ Payment received — <b>{payment.days_added} day(s)</b> added.\n"
        f"Active until <b>{user.expires_at:%Y-%m-%d %H:%M UTC}</b>."
    )


# ---------- YooKassa redirect-flow ----------
@router.callback_query(F.data == "pay:yookassa")
async def cb_pay_yookassa(
    cb: CallbackQuery, yookassa: YooKassaProvider
) -> None:
    await cb.answer()
    if cb.message is None or cb.from_user is None:
        return
    if not yookassa.enabled:
        await cb.message.answer("YooKassa is currently unavailable.")
        return
    inv = await yookassa.create_invoice(cb.from_user.id)
    await cb.message.answer(
        "Open the link below to pay via card. "
        "After successful payment your subscription will be activated automatically.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"💳 Pay {inv.amount}₽", url=inv.pay_url or "")],
                [InlineKeyboardButton(text="🔄 I've paid (refresh)", callback_data="profile")],
            ]
        ),
    )


# ---------- CryptoBot ----------
@router.callback_query(F.data == "pay:cryptobot")
async def cb_pay_cryptobot(
    cb: CallbackQuery, cryptobot: CryptoBotProvider
) -> None:
    await cb.answer()
    if cb.message is None or cb.from_user is None:
        return
    if not cryptobot.enabled:
        await cb.message.answer("Crypto payments are currently unavailable.")
        return
    inv = await cryptobot.create_invoice(cb.from_user.id)
    await cb.message.answer(
        "Pay in crypto via @CryptoBot — your subscription activates "
        "automatically after confirmation.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"🪙 Pay {inv.amount} {inv.currency}", url=inv.pay_url or "")],
                [InlineKeyboardButton(text="🔄 I've paid (refresh)", callback_data="profile")],
            ]
        ),
    )
