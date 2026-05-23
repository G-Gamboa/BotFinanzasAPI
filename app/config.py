from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
