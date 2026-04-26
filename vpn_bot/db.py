"""SQLite-backed storage for users, peers, and payment records."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id           INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    created_at      TEXT NOT NULL,
    expires_at      TEXT,                       -- ISO8601; NULL = no active subscription
    trial_used      INTEGER NOT NULL DEFAULT 0,
    is_blocked      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS peers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id           INTEGER NOT NULL,
    name            TEXT NOT NULL,              -- friendly device label
    private_key     TEXT NOT NULL,
    public_key      TEXT NOT NULL UNIQUE,
    preshared_key   TEXT,
    address         TEXT NOT NULL UNIQUE,       -- e.g. 10.13.13.5/32
    created_at      TEXT NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_peers_tg_id ON peers(tg_id);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id           INTEGER NOT NULL,
    provider        TEXT NOT NULL,              -- 'stars' | 'yookassa' | 'cryptobot'
    external_id     TEXT,                       -- provider-side id
    amount          REAL NOT NULL,
    currency        TEXT NOT NULL,              -- 'XTR' | 'RUB' | 'USDT' | 'TON' | 'BTC' ...
    status          TEXT NOT NULL,              -- 'pending' | 'paid' | 'failed' | 'refunded'
    days_added      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    paid_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_payments_tg_id ON payments(tg_id);
CREATE INDEX IF NOT EXISTS idx_payments_external ON payments(provider, external_id);
"""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _parse(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s)


@dataclass(slots=True)
class User:
    tg_id: int
    username: str | None
    first_name: str | None
    created_at: dt.datetime
    expires_at: dt.datetime | None
    trial_used: bool
    is_blocked: bool

    def is_active(self, now: dt.datetime | None = None) -> bool:
        if self.is_blocked or self.expires_at is None:
            return False
        return self.expires_at > (now or dt.datetime.now(dt.UTC))

    def days_left(self) -> int:
        if not self.expires_at:
            return 0
        delta = self.expires_at - dt.datetime.now(dt.UTC)
        return max(0, int(delta.total_seconds() // 86_400))


@dataclass(slots=True)
class Peer:
    id: int
    tg_id: int
    name: str
    private_key: str
    public_key: str
    preshared_key: str | None
    address: str
    created_at: dt.datetime
    revoked: bool


@dataclass(slots=True)
class Payment:
    id: int
    tg_id: int
    provider: str
    external_id: str | None
    amount: float
    currency: str
    status: str
    days_added: int
    created_at: dt.datetime
    paid_at: dt.datetime | None


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        await self._db.close()

    # ---------- users ----------
    async def upsert_user(
        self, tg_id: int, username: str | None, first_name: str | None
    ) -> User:
        row = await self._db.execute_fetchall(
            "SELECT tg_id FROM users WHERE tg_id=?", (tg_id,)
        )
        if not list(row):
            await self._db.execute(
                "INSERT INTO users(tg_id, username, first_name, created_at) VALUES (?,?,?,?)",
                (tg_id, username, first_name, _now()),
            )
        else:
            await self._db.execute(
                "UPDATE users SET username=?, first_name=? WHERE tg_id=?",
                (username, first_name, tg_id),
            )
        await self._db.commit()
        u = await self.get_user(tg_id)
        assert u is not None
        return u

    async def get_user(self, tg_id: int) -> User | None:
        async with self._db.execute(
            "SELECT * FROM users WHERE tg_id=?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return User(
            tg_id=row["tg_id"],
            username=row["username"],
            first_name=row["first_name"],
            created_at=_parse(row["created_at"]) or dt.datetime.now(dt.UTC),
            expires_at=_parse(row["expires_at"]),
            trial_used=bool(row["trial_used"]),
            is_blocked=bool(row["is_blocked"]),
        )

    async def grant_trial(self, tg_id: int, days: int) -> User:
        user = await self.get_user(tg_id)
        assert user is not None
        if user.trial_used:
            return user
        new_expiry = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
        await self._db.execute(
            "UPDATE users SET expires_at=?, trial_used=1 WHERE tg_id=?",
            (new_expiry.isoformat(), tg_id),
        )
        await self._db.commit()
        u = await self.get_user(tg_id)
        assert u is not None
        return u

    async def extend_subscription(self, tg_id: int, days: int) -> User:
        user = await self.get_user(tg_id)
        assert user is not None
        now = dt.datetime.now(dt.UTC)
        base = user.expires_at if user.expires_at and user.expires_at > now else now
        new_expiry = base + dt.timedelta(days=days)
        await self._db.execute(
            "UPDATE users SET expires_at=? WHERE tg_id=?",
            (new_expiry.isoformat(), tg_id),
        )
        await self._db.commit()
        u = await self.get_user(tg_id)
        assert u is not None
        return u

    async def block_user(self, tg_id: int, blocked: bool = True) -> None:
        await self._db.execute(
            "UPDATE users SET is_blocked=? WHERE tg_id=?", (1 if blocked else 0, tg_id)
        )
        await self._db.commit()

    async def list_users(self) -> list[User]:
        async with self._db.execute("SELECT * FROM users ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        return [
            User(
                tg_id=r["tg_id"],
                username=r["username"],
                first_name=r["first_name"],
                created_at=_parse(r["created_at"]) or dt.datetime.now(dt.UTC),
                expires_at=_parse(r["expires_at"]),
                trial_used=bool(r["trial_used"]),
                is_blocked=bool(r["is_blocked"]),
            )
            for r in rows
        ]

    async def list_expired_active(self) -> list[User]:
        """Users whose subscription has lapsed but whose peers are not yet revoked."""
        users = await self.list_users()
        now = dt.datetime.now(dt.UTC)
        return [u for u in users if u.expires_at and u.expires_at <= now]

    # ---------- peers ----------
    async def list_peers(self, tg_id: int | None = None, only_active: bool = True) -> list[Peer]:
        sql = "SELECT * FROM peers"
        params: tuple[object, ...] = ()
        clauses: list[str] = []
        if tg_id is not None:
            clauses.append("tg_id=?")
            params += (tg_id,)
        if only_active:
            clauses.append("revoked=0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            Peer(
                id=r["id"],
                tg_id=r["tg_id"],
                name=r["name"],
                private_key=r["private_key"],
                public_key=r["public_key"],
                preshared_key=r["preshared_key"],
                address=r["address"],
                created_at=_parse(r["created_at"]) or dt.datetime.now(dt.UTC),
                revoked=bool(r["revoked"]),
            )
            for r in rows
        ]

    async def create_peer(
        self,
        tg_id: int,
        name: str,
        private_key: str,
        public_key: str,
        preshared_key: str | None,
        address: str,
    ) -> Peer:
        await self._db.execute(
            "INSERT INTO peers(tg_id, name, private_key, public_key, preshared_key, address, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (tg_id, name, private_key, public_key, preshared_key, address, _now()),
        )
        await self._db.commit()
        peers = [p for p in await self.list_peers(tg_id, only_active=False) if p.public_key == public_key]
        assert peers
        return peers[-1]

    async def revoke_peer(self, peer_id: int) -> None:
        await self._db.execute("UPDATE peers SET revoked=1 WHERE id=?", (peer_id,))
        await self._db.commit()

    async def revoke_user_peers(self, tg_id: int) -> int:
        cur = await self._db.execute(
            "UPDATE peers SET revoked=1 WHERE tg_id=? AND revoked=0", (tg_id,)
        )
        await self._db.commit()
        return cur.rowcount or 0

    # ---------- payments ----------
    async def create_payment(
        self,
        tg_id: int,
        provider: str,
        amount: float,
        currency: str,
        days_added: int,
        external_id: str | None = None,
    ) -> int:
        cur = await self._db.execute(
            "INSERT INTO payments(tg_id, provider, external_id, amount, currency, status, days_added, created_at)"
            " VALUES (?,?,?,?,?, 'pending', ?, ?)",
            (tg_id, provider, external_id, amount, currency, days_added, _now()),
        )
        await self._db.commit()
        return cur.lastrowid or 0

    async def mark_payment_paid(self, payment_id: int, external_id: str | None = None) -> None:
        if external_id is not None:
            await self._db.execute(
                "UPDATE payments SET status='paid', paid_at=?, external_id=? WHERE id=?",
                (_now(), external_id, payment_id),
            )
        else:
            await self._db.execute(
                "UPDATE payments SET status='paid', paid_at=? WHERE id=?",
                (_now(), payment_id),
            )
        await self._db.commit()

    async def get_payment(self, payment_id: int) -> Payment | None:
        async with self._db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return Payment(
            id=r["id"],
            tg_id=r["tg_id"],
            provider=r["provider"],
            external_id=r["external_id"],
            amount=r["amount"],
            currency=r["currency"],
            status=r["status"],
            days_added=r["days_added"],
            created_at=_parse(r["created_at"]) or dt.datetime.now(dt.UTC),
            paid_at=_parse(r["paid_at"]),
        )

    async def get_payment_by_external(
        self, provider: str, external_id: str
    ) -> Payment | None:
        async with self._db.execute(
            "SELECT * FROM payments WHERE provider=? AND external_id=?", (provider, external_id)
        ) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return Payment(
            id=r["id"],
            tg_id=r["tg_id"],
            provider=r["provider"],
            external_id=r["external_id"],
            amount=r["amount"],
            currency=r["currency"],
            status=r["status"],
            days_added=r["days_added"],
            created_at=_parse(r["created_at"]) or dt.datetime.now(dt.UTC),
            paid_at=_parse(r["paid_at"]),
        )
