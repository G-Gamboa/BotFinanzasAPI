from typing import Any

from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str
    data: Any | None = None
