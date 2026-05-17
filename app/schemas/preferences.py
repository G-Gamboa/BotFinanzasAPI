from typing import Literal
from pydantic import BaseModel, Field

DefaultTab = Literal["movimientos", "deudas", "dashboard", "prestamos"]


class PreferencesResponse(BaseModel):
    telegram_user_id: int
    show_amounts_default: bool
    default_tab: str
    usd_to_gtq: float
    theme_key: str | None = None
    tab_order: list[str] | None = None


class PreferencesUpdateRequest(BaseModel):
    telegram_user_id: int
    show_amounts_default: bool
    default_tab: DefaultTab
    usd_to_gtq: float = Field(gt=0)
    theme_key: str | None = None
    tab_order: list[str] | None = None


class PreferencesUpdateResponse(BaseModel):
    ok: bool
    message: str