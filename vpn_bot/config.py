"""Application configuration (loaded from env / .env)."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from .env or environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Telegram ---
    bot_token: str = Field(alias="BOT_TOKEN")
    bot_admin_ids: list[int] = Field(default_factory=list, alias="BOT_ADMIN_IDS")

    # --- WireGuard ---
    wg_server_host: str = Field(alias="WG_SERVER_HOST")
    wg_server_port: int = Field(default=51820, alias="WG_SERVER_PORT")
    wg_server_pubkey: str = Field(alias="WG_SERVER_PUBKEY")
    wg_interface: str = Field(default="wg0", alias="WG_INTERFACE")
    wg_network: str = Field(default="10.13.13.0/24", alias="WG_NETWORK")
    wg_dns: str = Field(default="1.1.1.1, 8.8.8.8", alias="WG_DNS")
    wg_allowed_ips: str = Field(default="0.0.0.0/0, ::/0", alias="WG_ALLOWED_IPS")
    wg_peer_keepalive: int = Field(default=25, alias="WG_PEER_KEEPALIVE")
    wg_config_path: Path = Field(default=Path("/etc/wireguard/wg0.conf"), alias="WG_CONFIG_PATH")
    wg_reload_mode: str = Field(default="wg-quick", alias="WG_RELOAD_MODE")
    wg_ssh_user: str = Field(default="root", alias="WG_SSH_USER")
    wg_ssh_port: int = Field(default=22, alias="WG_SSH_PORT")
    wg_ssh_key: Path | None = Field(default=None, alias="WG_SSH_KEY")

    # --- Subscription ---
    trial_days: int = Field(default=3, alias="TRIAL_DAYS")
    subscription_days: int = Field(default=30, alias="SUBSCRIPTION_DAYS")
    subscription_price_stars: int = Field(default=150, alias="SUBSCRIPTION_PRICE_STARS")
    subscription_price_rub: int = Field(default=199, alias="SUBSCRIPTION_PRICE_RUB")
    subscription_price_usd: float = Field(default=2.49, alias="SUBSCRIPTION_PRICE_USD")

    # --- YooKassa ---
    yookassa_shop_id: str | None = Field(default=None, alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str | None = Field(default=None, alias="YOOKASSA_SECRET_KEY")
    yookassa_return_url: str = Field(default="https://t.me/", alias="YOOKASSA_RETURN_URL")

    # --- CryptoBot ---
    cryptobot_token: str | None = Field(default=None, alias="CRYPTOBOT_TOKEN")
    cryptobot_testnet: bool = Field(default=False, alias="CRYPTOBOT_TESTNET")

    # --- Webhook server ---
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8081, alias="WEBHOOK_PORT")
    webhook_public_url: str | None = Field(default=None, alias="WEBHOOK_PUBLIC_URL")

    # --- Storage ---
    db_path: Path = Field(default=Path("./data/vpn-bot.db"), alias="DB_PATH")

    @field_validator("bot_admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: object) -> list[int]:
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        raise TypeError(f"Unsupported admin ids: {v!r}")

    @property
    def yookassa_enabled(self) -> bool:
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    @property
    def cryptobot_enabled(self) -> bool:
        return bool(self.cryptobot_token)


def load_settings() -> Settings:
    return Settings()
