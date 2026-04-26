"""WireGuard peer management.

Generates ed25519 keypairs in pure-Python (NaCl/Curve25519 via :mod:`cryptography`),
allocates IPs, writes ``wg0.conf``, and reloads the WireGuard interface.
"""
from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import logging
import secrets
import shutil
import textwrap
from pathlib import Path

import qrcode
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from .config import Settings
from .db import Database, Peer

log = logging.getLogger(__name__)


def _gen_keypair() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) in WireGuard's encoding."""
    sk = X25519PrivateKey.generate()
    sk_raw = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pk_raw = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(sk_raw).decode(), base64.b64encode(pk_raw).decode()


def _gen_psk() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def derive_pubkey(private_b64: str) -> str:
    raw = base64.b64decode(private_b64)
    sk = X25519PrivateKey.from_private_bytes(raw)
    pk_raw = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(pk_raw).decode()


def _validate_pubkey(b64: str) -> None:
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise ValueError("invalid public key length")
    X25519PublicKey.from_public_bytes(raw)


class WireGuardManager:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.network = ipaddress.ip_network(settings.wg_network, strict=False)

    # --- IP allocation ----
    async def _next_address(self) -> str:
        used: set[str] = set()
        for p in await self.db.list_peers(only_active=False):
            used.add(p.address.split("/")[0])
        # reserve .1 for the server itself
        server_ip = next(self.network.hosts())
        used.add(str(server_ip))
        for host in self.network.hosts():
            if str(host) not in used:
                return f"{host}/32"
        raise RuntimeError("No free IPs in WG_NETWORK")

    # --- Peer CRUD ----
    async def create_peer(self, tg_id: int, name: str = "device") -> Peer:
        priv, pub = _gen_keypair()
        psk = _gen_psk()
        address = await self._next_address()
        peer = await self.db.create_peer(
            tg_id=tg_id,
            name=name,
            private_key=priv,
            public_key=pub,
            preshared_key=psk,
            address=address,
        )
        log.info("Created peer %s for user %s at %s", peer.id, tg_id, address)
        await self.sync_server_config()
        return peer

    async def revoke_peer(self, peer_id: int) -> None:
        await self.db.revoke_peer(peer_id)
        await self.sync_server_config()

    async def revoke_user_peers(self, tg_id: int) -> int:
        n = await self.db.revoke_user_peers(tg_id)
        if n:
            await self.sync_server_config()
        return n

    # --- Client configuration rendering ----
    def render_client_config(self, peer: Peer) -> str:
        s = self.settings
        return textwrap.dedent(
            f"""\
            [Interface]
            PrivateKey = {peer.private_key}
            Address = {peer.address}
            DNS = {s.wg_dns}

            [Peer]
            PublicKey = {s.wg_server_pubkey}
            PresharedKey = {peer.preshared_key}
            AllowedIPs = {s.wg_allowed_ips}
            Endpoint = {s.wg_server_host}:{s.wg_server_port}
            PersistentKeepalive = {s.wg_peer_keepalive}
            """
        )

    @staticmethod
    def render_qr_png(text: str) -> bytes:
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # --- Server-side wg0.conf rendering ----
    async def render_server_config(self, server_private_key: str | None = None) -> str:
        """Render the full ``wg0.conf`` for the server.

        ``server_private_key`` should normally NOT be passed by the bot — keep
        it on the VPS only. The bot never persists the server private key.
        Pass an empty string to keep the existing ``[Interface]`` block intact
        (bot only rewrites the [Peer] section when ``WG_RELOAD_MODE=ssh`` is
        used and the script reads the existing key on the server side).
        """
        s = self.settings
        peers = await self.db.list_peers(only_active=True)
        peer_blocks = []
        for p in peers:
            psk_line = f"\nPresharedKey = {p.preshared_key}" if p.preshared_key else ""
            peer_blocks.append(
                textwrap.dedent(
                    f"""\
                    [Peer]
                    # tg_id={p.tg_id} name={p.name}
                    PublicKey = {p.public_key}{psk_line}
                    AllowedIPs = {p.address}
                    """
                )
            )

        server_iface = next(self.network.hosts())
        iface_priv = server_private_key if server_private_key is not None else "REPLACE_ON_HOST"
        head = textwrap.dedent(
            f"""\
            [Interface]
            Address = {server_iface}/{self.network.prefixlen}
            ListenPort = {s.wg_server_port}
            PrivateKey = {iface_priv}
            SaveConfig = false
            PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
            PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

            """
        )
        return head + "\n".join(peer_blocks)

    async def sync_server_config(self) -> None:
        """Write a peers-only file or full config and reload the interface."""
        mode = self.settings.wg_reload_mode
        if mode == "noop":
            log.info("wg sync: noop mode — skipping reload")
            return
        peers = await self.db.list_peers(only_active=True)
        peer_section = "\n".join(self._peer_block(p) for p in peers)
        peers_file = self.settings.wg_config_path.parent / "peers.conf"

        if mode == "wg-quick":
            if not shutil.which("wg") or not shutil.which("wg-quick"):
                log.warning("wg/wg-quick not found in PATH; skipping reload")
                return
            try:
                peers_file.parent.mkdir(parents=True, exist_ok=True)
                peers_file.write_text(peer_section)
            except PermissionError:
                log.warning("Cannot write %s (permission denied)", peers_file)
                return
            await self._run_local_reload(peers_file)
            return

        if mode == "ssh":
            await self._run_ssh_reload(peer_section)
            return

        log.warning("Unknown WG_RELOAD_MODE=%s — skipping", mode)

    @staticmethod
    def _peer_block(p: Peer) -> str:
        psk = f"\nPresharedKey = {p.preshared_key}" if p.preshared_key else ""
        return textwrap.dedent(
            f"""\
            [Peer]
            PublicKey = {p.public_key}{psk}
            AllowedIPs = {p.address}
            """
        )

    async def _run_local_reload(self, peers_file: Path) -> None:
        # The server's [Interface] section lives in wg_config_path. Apply peers.
        iface = self.settings.wg_interface
        cmd = (
            f"sudo bash -c 'wg syncconf {iface} <(wg-quick strip {self.settings.wg_config_path})'"
        )
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            log.error("wg syncconf failed: %s / %s", out.decode(), err.decode())

    async def _run_ssh_reload(self, peer_section: str) -> None:
        s = self.settings
        cmd_remote = (
            "umask 077 && "
            f"cat > /tmp/peers.conf && "
            f"awk 'BEGIN{{p=0}} /^\\[Peer\\]/{{p=1; exit}} {{print}}' {s.wg_config_path} > /tmp/wg0.head && "
            "cat /tmp/wg0.head /tmp/peers.conf > /tmp/wg0.new && "
            f"mv /tmp/wg0.new {s.wg_config_path} && "
            f"wg syncconf {s.wg_interface} <(wg-quick strip {s.wg_config_path})"
        )
        ssh_cmd = ["ssh"]
        if s.wg_ssh_key:
            ssh_cmd += ["-i", str(s.wg_ssh_key)]
        ssh_cmd += [
            "-p", str(s.wg_ssh_port),
            "-o", "StrictHostKeyChecking=accept-new",
            f"{s.wg_ssh_user}@{s.wg_server_host}",
            cmd_remote,
        ]
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate(input=peer_section.encode())
        if proc.returncode != 0:
            log.error("ssh reload failed: %s / %s", out.decode(), err.decode())
