"""User-facing /start, /profile, /getconfig flow."""
from __future__ import annotations

import datetime as dt
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..config import Settings
from ..db import Database
from ..wireguard import WireGuardManager

log = logging.getLogger(__name__)
router = Router(name="user")


def _main_menu(active: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if active:
        rows.append([InlineKeyboardButton(text="📥 Get config", callback_data="get_config")])
    rows.append([InlineKeyboardButton(text="💳 Buy / Extend", callback_data="buy")])
    rows.append([InlineKeyboardButton(text="ℹ️ My status", callback_data="profile")])
    rows.append([InlineKeyboardButton(text="❓ Help", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_status(expires_at: dt.datetime | None) -> str:
    if expires_at is None:
        return "❌ Subscription: <b>not active</b>"
    now = dt.datetime.now(dt.UTC)
    if expires_at <= now:
        return f"❌ Subscription: <b>expired</b> on {expires_at:%Y-%m-%d %H:%M UTC}"
    days = (expires_at - now).days
    return (
        f"✅ Subscription active — <b>{days} day(s)</b> left "
        f"(until {expires_at:%Y-%m-%d %H:%M UTC})"
    )


@router.message(CommandStart())
async def cmd_start(msg: Message, db: Database, settings: Settings, wg: WireGuardManager) -> None:
    if msg.from_user is None:
        return
    user = await db.upsert_user(
        tg_id=msg.from_user.id,
        username=msg.from_user.username,
        first_name=msg.from_user.first_name,
    )
    greeting = (
        f"👋 Hi <b>{msg.from_user.first_name or 'friend'}</b>!\n\n"
        "I'm your <b>WireGuard VPN</b> bot. I issue personal configs and renew "
        "subscriptions.\n\n"
    )
    if not user.trial_used:
        user = await db.grant_trial(user.tg_id, settings.trial_days)
        greeting += (
            f"🎁 <b>Free trial activated</b> — {settings.trial_days} day(s).\n"
            "Press <b>📥 Get config</b> to receive your WireGuard file + QR.\n\n"
        )
        # auto-create one peer for them
        if not await db.list_peers(user.tg_id, only_active=True):
            await wg.create_peer(user.tg_id, name="default")
    greeting += _format_status(user.expires_at)
    await msg.answer(greeting, reply_markup=_main_menu(user.is_active()))


@router.callback_query(F.data == "profile")
@router.message(Command("profile"))
async def show_profile(
    event: Message | CallbackQuery, db: Database
) -> None:
    user_obj = event.from_user
    msg = event if isinstance(event, Message) else event.message
    if user_obj is None or msg is None:
        return
    user = await db.get_user(user_obj.id)
    if user is None:
        await msg.answer("Use /start first.")
        return
    peers = await db.list_peers(user.tg_id, only_active=True)
    text = (
        f"<b>Your account</b>\n"
        f"{_format_status(user.expires_at)}\n"
        f"📱 Active devices: <b>{len(peers)}</b>\n"
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if isinstance(msg, Message):
            await msg.edit_text(text, reply_markup=_main_menu(user.is_active()))
    else:
        await msg.answer(text, reply_markup=_main_menu(user.is_active()))


async def _send_config(msg: Message, db: Database, wg: WireGuardManager, tg_id: int) -> None:
    peers = await db.list_peers(tg_id, only_active=True)
    if not peers:
        peer = await wg.create_peer(tg_id, name="default")
    else:
        peer = peers[0]
    text = wg.render_client_config(peer)
    await msg.answer_document(
        BufferedInputFile(text.encode(), filename=f"vpn-{peer.id}.conf"),
        caption=(
            "🔐 Your WireGuard config.\n"
            "1) Install the official <b>WireGuard</b> app (or use our APK).\n"
            "2) Tap + → <b>Import from file</b> (or scan the QR below).\n"
            "3) Toggle the tunnel on."
        ),
    )
    qr = wg.render_qr_png(text)
    await msg.answer_photo(
        BufferedInputFile(qr, filename=f"vpn-{peer.id}.png"),
        caption="Scan this QR from the WireGuard app to import.",
    )


@router.callback_query(F.data == "get_config")
async def cb_get_config(cb: CallbackQuery, db: Database, wg: WireGuardManager) -> None:
    await cb.answer()
    if cb.from_user is None or cb.message is None:
        return
    user = await db.get_user(cb.from_user.id)
    if not isinstance(cb.message, Message):
        return
    if user is None or not user.is_active():
        await cb.message.answer(
            "❌ You don't have an active subscription. Tap 💳 <b>Buy / Extend</b>."
        )
        return
    await _send_config(cb.message, db, wg, cb.from_user.id)


@router.message(Command("getconfig"))
async def cmd_getconfig(msg: Message, db: Database, wg: WireGuardManager) -> None:
    if msg.from_user is None:
        return
    user = await db.get_user(msg.from_user.id)
    if user is None or not user.is_active():
        await msg.answer("❌ No active subscription. /start to get a trial or /buy.")
        return
    await _send_config(msg, db, wg, msg.from_user.id)


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery) -> None:
    await cb.answer()
    if cb.message is None:
        return
    await cb.message.answer(
        "<b>How it works</b>\n\n"
        "• /start — register / claim free trial\n"
        "• /getconfig — download your WireGuard config + QR\n"
        "• /buy — extend or renew subscription\n"
        "• /profile — see status + days left\n\n"
        "💡 You can install the official <b>WireGuard</b> app from your store, "
        "or use our branded Android APK from the channel."
    )
