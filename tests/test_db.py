"""Database CRUD tests."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from vpn_bot.db import Database


@pytest.mark.asyncio
async def test_user_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "u.db")
    await db.connect()
    try:
        u = await db.upsert_user(tg_id=42, username="bob", first_name="Bob")
        assert u.tg_id == 42
        assert not u.is_active()
        assert not u.trial_used

        u = await db.grant_trial(42, days=3)
        assert u.trial_used
        assert u.is_active()
        assert u.expires_at is not None
        assert u.expires_at > dt.datetime.now(dt.UTC)

        # Granting trial twice is a no-op
        before = u.expires_at
        u = await db.grant_trial(42, days=99)
        assert u.expires_at == before

        u = await db.extend_subscription(42, days=30)
        assert (u.expires_at - before).days >= 29
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_payment_flow(tmp_path: Path) -> None:
    db = Database(tmp_path / "p.db")
    await db.connect()
    try:
        await db.upsert_user(tg_id=10, username=None, first_name=None)
        pid = await db.create_payment(
            tg_id=10,
            provider="cryptobot",
            amount=2.49,
            currency="USDT",
            days_added=30,
            external_id="inv-abc",
        )
        p = await db.get_payment(pid)
        assert p is not None
        assert p.status == "pending"

        await db.mark_payment_paid(pid, external_id="inv-abc")
        p2 = await db.get_payment(pid)
        assert p2 is not None
        assert p2.status == "paid"
        assert p2.paid_at is not None

        p3 = await db.get_payment_by_external("cryptobot", "inv-abc")
        assert p3 is not None
        assert p3.id == pid
    finally:
        await db.close()
