"""Smoke tests for WG keygen and config rendering (no network, no daemon)."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from vpn_bot.config import Settings
from vpn_bot.db import Database
from vpn_bot.wireguard import WireGuardManager, derive_pubkey


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        BOT_TOKEN="123:test",
        WG_SERVER_HOST="vpn.example.com",
        WG_SERVER_PUBKEY="A" * 43 + "=",
        WG_NETWORK="10.13.13.0/24",
        WG_RELOAD_MODE="noop",
        WG_CONFIG_PATH=tmp_path / "wg0.conf",
        DB_PATH=tmp_path / "test.db",
    )


@pytest.mark.asyncio
async def test_create_peer_and_render(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.connect()
    try:
        await db.upsert_user(tg_id=1, username="alice", first_name="Alice")
        wg = WireGuardManager(settings, db)
        peer = await wg.create_peer(tg_id=1, name="laptop")

        # public key derives correctly from private key
        assert derive_pubkey(peer.private_key) == peer.public_key
        # raw key length must be 32 bytes
        assert len(base64.b64decode(peer.private_key)) == 32
        # IP allocated inside the network and not the .1 server address
        assert peer.address.endswith("/32")
        assert peer.address.split("/")[0] != "10.13.13.1"

        cfg = wg.render_client_config(peer)
        assert "[Interface]" in cfg
        assert peer.private_key in cfg
        assert "Endpoint = vpn.example.com:51820" in cfg
        assert peer.preshared_key in cfg

        png = wg.render_qr_png(cfg)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unique_addresses(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.connect()
    try:
        await db.upsert_user(tg_id=1, username=None, first_name=None)
        await db.upsert_user(tg_id=2, username=None, first_name=None)
        wg = WireGuardManager(settings, db)
        a = await wg.create_peer(tg_id=1)
        b = await wg.create_peer(tg_id=2)
        assert a.address != b.address
    finally:
        await db.close()
