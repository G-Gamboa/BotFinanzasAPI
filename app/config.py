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
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
