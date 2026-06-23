import json
import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_int_list(v: object) -> list[int]:
    """Parse a list[int] tolerantly from env vars.

    Accepts all common formats found in .env files:
      [1, 2]          → JSON array (standard)
      ['1', '2']      → single-quoted strings
      ["1", "2"]      → double-quoted strings
      1,2             → bare comma-separated
      1               → single bare integer
    """
    if isinstance(v, list):
        return [int(x) for x in v]
    if isinstance(v, (int, float)):
        return [int(v)]
    s = str(v).strip()
    if not s:
        return []
    # Normalise single quotes → double quotes so json.loads can handle it
    normalised = s.replace("'", '"')
    try:
        parsed = json.loads(normalised)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
        return [int(parsed)]
    except json.JSONDecodeError:
        pass
    # Fallback: strip brackets/quotes/whitespace and split on commas
    cleaned = re.sub(r'[\[\]\s\'"]+', '', s)
    return [int(x) for x in cleaned.split(',') if x]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    env: str = Field(default="development", alias="ENV")
    tz_name: str = Field(default="America/Guatemala", alias="TZ")
    usd_to_gtq: float = Field(default=7.7, alias="USD_TO_GTQ")
    cors_origins: list[str] = Field(default=["*"], alias="CORS_ORIGINS")
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    admin_telegram_ids: list[int] = Field(default=[], alias="ADMIN_TELEGRAM_IDS")
    admin_secret: str = Field(default="", alias="ADMIN_SECRET")
    # IDs exentos de suscripción (acceso permanente sin pago)
    private_palette_user_ids: list[int] = Field(default=[], alias="PRIVATE_PALETTE_USER_IDS")
    # Registration via Telegram Stars
    registration_stars_price: int = Field(default=100, alias="REGISTRATION_STARS_PRICE")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    cron_secret: str = Field(default="", alias="CRON_SECRET")

    @field_validator("admin_telegram_ids", "private_palette_user_ids", mode="before")
    @classmethod
    def parse_int_list(cls, v: object) -> list[int]:
        return _parse_int_list(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
