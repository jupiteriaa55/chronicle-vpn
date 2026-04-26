# Chronicle VPN

A self-hosted **WireGuard VPN service** managed by a **Telegram bot**, with
built-in payments via **Telegram Stars**, **YooKassa** (RU cards), and
**CryptoBot** (USDT / TON / BTC). Comes with a branded **Android client** built
with Capacitor that imports `.conf` files directly into the WireGuard tunnel
service.

## Architecture

```
┌────────────┐   /start /buy /getconfig    ┌──────────────────┐
│  Telegram  │ ─────────────────────────►  │  bot (Python)    │
└────────────┘ ◄─── invoice + .conf + QR   │  aiogram3        │
                                           │  + FastAPI       │
                                           │  webhooks        │
                                           └──────┬───────────┘
                                                  │ writes peers
                                                  │ wg syncconf
                                                  ▼
                                           ┌──────────────────┐
                                           │ WireGuard server │
                                           │ wg-quick@wg0     │
                                           │ kernel tunnel    │
                                           └──────────────────┘
```

The bot stores users / peers / payments in **SQLite**, generates Curve25519
keypairs locally, allocates IPs from `WG_NETWORK`, writes `wg0.conf`, and
calls `wg syncconf` to reload the running interface without dropping existing
tunnels.

## Repo layout

| Path                       | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `vpn_bot/`                 | Python package (bot + payment providers + webhooks)  |
| `vpn_bot/wireguard.py`     | Peer keygen, IP allocation, wg syncconf              |
| `vpn_bot/payments/`        | Stars / YooKassa / CryptoBot providers               |
| `vpn_bot/handlers/`        | aiogram routers (user / payments / admin)            |
| `vpn_bot/webhook.py`       | FastAPI app for YooKassa + CryptoBot callbacks       |
| `vpn_bot/scheduler.py`     | Background expiry / reminder loop                    |
| `scripts/wg-install.sh`    | Bootstrap WireGuard on a fresh Ubuntu/Debian VPS     |
| `Dockerfile`, `compose.yml`| Container build for the bot                          |
| `android/`                 | Capacitor-wrapped Android APK (added in next step)   |
| `web/`                     | Static landing/PWA used as Capacitor webview         |

## Quick start

### 1. Set up the VPN server (on the VPS)

```bash
ssh root@your-vps
git clone https://github.com/jupiteriaa55/chronicle-vpn.git
cd chronicle-vpn
sudo bash scripts/wg-install.sh
```

The script prints a summary at the end with `WG_SERVER_HOST` /
`WG_SERVER_PUBKEY` — copy them into the bot's `.env`.

### 2. Configure the bot

```bash
cp .env.example .env
$EDITOR .env  # at minimum: BOT_TOKEN, BOT_ADMIN_IDS, WG_SERVER_*
```

Optional payment creds:

- **Telegram Stars** — works automatically with `BOT_TOKEN`, no setup.
- **YooKassa** — get `YOOKASSA_SHOP_ID` + `YOOKASSA_SECRET_KEY` from
  <https://yookassa.ru/my/api>. Register webhook URL
  `https://your-domain/webhook/yookassa` in YooKassa dashboard for the
  `payment.succeeded` event.
- **CryptoBot** — open [@CryptoBot](https://t.me/CryptoBot) → *Crypto Pay* →
  *Create App* → copy token to `CRYPTOBOT_TOKEN`. Register webhook URL
  `https://your-domain/webhook/cryptobot`.

### 3. Run the bot

```bash
docker compose up -d --build
```

It opens UDP nothing (the bot doesn't tunnel; the kernel does) and HTTP
`8081` for webhook callbacks. Front it with Caddy/Nginx for TLS.

### 4. Try it in Telegram

Send `/start` to your bot → claim free trial → tap **📥 Get config** to
receive the `.conf` file + QR. Either:

- Install the official **WireGuard** app and *Import from file* / *Scan QR*.
- Or sideload our Android APK from the latest CI run (`android/`).

## Admin commands

| Command                       | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| `/stats`                      | totals: users, active subs, peers        |
| `/list_users`                 | last 50 users with status                |
| `/grant <tg_id> <days>`       | extend subscription                      |
| `/revoke <tg_id>`             | revoke all peers (kick from VPN)         |
| `/block <tg_id> [unblock]`    | block / unblock                          |
| `/broadcast <text>`           | broadcast message                        |

Add yourself to `BOT_ADMIN_IDS` in `.env` to use these.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
mypy vpn_bot
pytest
```

## License

MIT — see `LICENSE`.
