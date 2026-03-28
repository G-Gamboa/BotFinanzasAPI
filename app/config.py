import json
from functools import lru_cache
from typing import List
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    bot_token: str = Field(alias='BOT_TOKEN')
    google_credentials_json: str = Field(alias='GOOGLE_CREDENTIALS_JSON')
    user_sheets_raw: str = Field(alias='USER_SHEETS')
    tz_name: str = Field(default='America/Guatemala', alias='TZ')
    usd_to_gtq: float = Field(default=7.7, alias="USD_TO_GTQ")
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    env: str = Field(default='development', alias='ENV')
    database_url: str = Field(alias="DATABASE_URL")


    @field_validator('google_credentials_json')
    @classmethod
    def validate_google_credentials_json(cls, value: str) -> str:
        json.loads(value)
        return value

    @property
    def google_credentials(self) -> dict:
        return json.loads(self.google_credentials_json)

    @property
    def user_sheets(self) -> dict[int, str]:
        raw = json.loads(self.user_sheets_raw)
        return {int(k): str(v) for k, v in raw.items()}

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)




    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

_settings = None

SHEET_INGRESOS = 'Ingresos'
SHEET_EGRESOS = 'Egresos'
SHEET_MOVIMIENTOS = 'Movimientos'
SHEET_CATEGORIAS = 'Categorías'
SHEET_DEUDAS = 'Deudas'

INV_CUENTAS_DEFAULT = {'Ugly', 'Binance', 'Osmo', 'Hapi'}
BOLSA_NORMAL = 'Normal'
AHORRO_CUENTA = 'Ahorro'
PRESTAMOS_CUENTA = 'Préstamos'

FUENTES_ING = ['Trabajo', 'Freelance', 'Negocios', 'Otros']
CATEG_ING = ['Salario', 'Proyecto', 'Ventas', 'Inversiones', 'Intereses', 'Préstamos', 'Otros']
METODOS = ['Efectivo', 'Transferencia']
BANCOS = ['BI', 'Banrural', 'Nexa', 'Zigi', 'GyT']
CATEG_EGR = [
    'Agua', 'Internet', 'Transporte', 'Comida', 'Casa', 'Chatarra', 'Supermercado',
    'Estudios', 'Mercado', 'Entretenimiento', 'Salud', 'Ropa', 'Zapatos',
    'Suscripciones', 'Salidas', 'Regalos', 'Otros'
]
CUENTAS = ['Efectivo', 'BI', 'Banrural', 'Nexa', 'Zigi', 'GyT', 'Ahorro', 'Préstamos']
PERSONAS_PRESTAMO = []


@lru_cache
def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
