from pydantic import BaseModel, Field
from typing import Optional


class MovementVoidRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class MovementUpdateRequest(BaseModel):
    movement_date: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=500)
    category_name: Optional[str] = Field(default=None, max_length=100)
    payment_method: Optional[str] = Field(default=None, max_length=50)