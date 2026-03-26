
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    users_configured: int


class MessageResponse(BaseModel):
    ok: bool = True
    message: str
    data: dict[str, Any] | None = None
