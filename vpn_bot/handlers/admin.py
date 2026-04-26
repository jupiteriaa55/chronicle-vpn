"""Admin commands: /stats, /list_users, /grant, /revoke, /block, /broadcast."""
from __future__ import annotations

import datetime as dt

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..config import Settings
from ..db import Database
from ..wireguard import WireGuardManager

router = Router(name="admin")


def _is_admin(settings: Settings, tg_id: int) -> bool:
    return tg_id in settings.bot_admin_ids


@router.message(Command("stats"))
async def cmd_stats(msg: Message, settings: Settings, db: Database) -> None:
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    users = await db.list_users()
    now = dt.datetime.now(dt.UTC)
    active = sum(1 for u in users if u.expires_at and u.expires_at > now and not u.is_blocked)
    trial_used = sum(1 for u in users if u.trial_used)
    peers = await db.list_peers(only_active=True)
    await msg.answer(
        "<b>📊 Stats</b>\n"
        f"Users total: <b>{len(users)}</b>\n"
        f"Active subs: <b>{active}</b>\n"
        f"Used trial: <b>{trial_used}</b>\n"
        f"Active peers: <b>{len(peers)}</b>"
    )


@router.message(Command("list_users"))
async def cmd_list_users(msg: Message, settings: Settings, db: Database) -> None:
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    users = await db.list_users()
    lines = []
    for u in users[:50]:
        status = (
            f"until {u.expires_at:%Y-%m-%d}" if u.expires_at else "no sub"
        )
        flag = "🚫" if u.is_blocked else "✅"
        uname = f"@{u.username}" if u.username else "—"
        lines.append(f"{flag} <code>{u.tg_id}</code> {uname} · {status}")
    text = "\n".join(lines) if lines else "No users yet."
    await msg.answer(f"<b>Users ({len(users)})</b>\n\n{text}")


@router.message(Command("grant"))
async def cmd_grant(
    msg: Message,
    command: CommandObject,
    settings: Settings,
    db: Database,
    wg: WireGuardManager,
) -> None:
    """/grant <tg_id> <days> — extend a subscription."""
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    args = (command.args or "").split()
    if len(args) != 2:
        await msg.answer("Usage: /grant &lt;tg_id&gt; &lt;days&gt;")
        return
    tg_id, days = int(args[0]), int(args[1])
    user = await db.get_user(tg_id)
    if user is None:
        await msg.answer(f"User {tg_id} not found.")
        return
    user = await db.extend_subscription(tg_id, days)
    if not await db.list_peers(tg_id, only_active=True):
        await wg.create_peer(tg_id, name="default")
    await msg.answer(
        f"✅ Granted {days} day(s) to <code>{tg_id}</code>. "
        f"Now active until {user.expires_at:%Y-%m-%d %H:%M UTC}."
    )


@router.message(Command("revoke"))
async def cmd_revoke(
    msg: Message,
    command: CommandObject,
    settings: Settings,
    db: Database,
    wg: WireGuardManager,
) -> None:
    """/revoke <tg_id> — revoke all peers (kick from VPN)."""
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    args = (command.args or "").split()
    if len(args) != 1:
        await msg.answer("Usage: /revoke &lt;tg_id&gt;")
        return
    tg_id = int(args[0])
    n = await wg.revoke_user_peers(tg_id)
    await msg.answer(f"Revoked {n} peer(s) for <code>{tg_id}</code>.")


@router.message(Command("block"))
async def cmd_block(
    msg: Message,
    command: CommandObject,
    settings: Settings,
    db: Database,
    wg: WireGuardManager,
) -> None:
    """/block <tg_id> [unblock] — block user and revoke their peers."""
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    args = (command.args or "").split()
    if not args:
        await msg.answer("Usage: /block &lt;tg_id&gt; [unblock]")
        return
    tg_id = int(args[0])
    unblock = len(args) > 1 and args[1].lower() == "unblock"
    await db.block_user(tg_id, blocked=not unblock)
    if not unblock:
        await wg.revoke_user_peers(tg_id)
    await msg.answer(
        f"{'Unblocked' if unblock else 'Blocked'} <code>{tg_id}</code>."
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(
    msg: Message,
    command: CommandObject,
    settings: Settings,
    db: Database,
    bot: Bot,
) -> None:
    if msg.from_user is None or not _is_admin(settings, msg.from_user.id):
        return
    text = command.args or ""
    if not text:
        await msg.answer("Usage: /broadcast &lt;message&gt;")
        return
    users = await db.list_users()
    sent = 0
    for u in users:
        try:
            await bot.send_message(u.tg_id, text)
            sent += 1
        except Exception:
            continue
    await msg.answer(f"Broadcast sent to {sent}/{len(users)} users.")
