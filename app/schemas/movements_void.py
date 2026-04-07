from pydantic import BaseModel
from typing import Optional


class MovementVoidRequest(BaseModel):
    reason: Optional[str] = None