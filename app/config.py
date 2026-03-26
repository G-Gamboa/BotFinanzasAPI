
import json
import os
from functools import lru_cache
from typing import Dict

from pydantic import BaseModel, Field


class Settings(BaseModel):
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    google_credentials_json: str = Field(default="", alias="GOOGLE_CREDENTIALS_JSON")
    user_sheets_raw: str = Field(default="{}", alias="USER_SHEETS")
    tz: str = Field(default="America/Guatemala", alias="TZ")
    env: str = Field(default="development", alias="ENV")
    api_base_url: str = Field(default="", alias="API_BASE_URL")
    cors_origins_raw: str = Field(default='["*"]', alias="CORS_ORIGINS")

    @property
    def user_sheets(self) -> Dict[int, str]:
        try:
            data = json.loads(self.user_sheets_raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("USER_SHEETS no es JSON válido") from exc
        return {int(k): str(v) for k, v in data.items()}

    @property
    def cors_origins(self) -> list[str]:
        try:
            data = json.loads(self.cors_origins_raw or '["*"]')
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
        return ["*"]


@lru_cache
def get_settings() -> Settings:
    data = {
        "BOT_TOKEN": os.getenv("BOT_TOKEN", ""),
        "GOOGLE_CREDENTIALS_JSON": os.getenv("GOOGLE_CREDENTIALS_JSON", ""),
        "USER_SHEETS": os.getenv("USER_SHEETS", "{}"),
        "TZ": os.getenv("TZ", "America/Guatemala"),
        "ENV": os.getenv("ENV", "development"),
        "API_BASE_URL": os.getenv("API_BASE_URL", ""),
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", '["*"]'),
    }
    return Settings(**data)
