from pydantic import BaseModel, Field
from typing import Optional


class MovementVoidRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)