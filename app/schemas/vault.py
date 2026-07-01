from datetime import datetime
from app.schemas import ResponseModel


class VaultConfigResponse(ResponseModel):
    salt: str
    dek_wrapped: str


class VaultSetupRequest(ResponseModel):
    telegram_user_id: int
    salt: str
    dek_wrapped: str


class VaultItemResponse(ResponseModel):
    id: int
    ciphertext: str
    updated_at: datetime


class VaultItemsResponse(ResponseModel):
    items: list[VaultItemResponse]


class VaultItemCreateRequest(ResponseModel):
    telegram_user_id: int
    ciphertext: str


class VaultItemUpdateRequest(ResponseModel):
    telegram_user_id: int
    ciphertext: str


class VaultActionResponse(ResponseModel):
    id: int
    ok: bool
