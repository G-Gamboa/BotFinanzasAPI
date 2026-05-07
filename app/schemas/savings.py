from pydantic import BaseModel, Field


class SavingsGoalItem(BaseModel):
    id: int
    name: str
    target_amount: float
    account_name: str | None
    current_amount: float
    is_active: bool


class SavingsGoalsResponse(BaseModel):
    items: list[SavingsGoalItem]


class SavingsGoalCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=150)
    target_amount: float = Field(gt=0)
    account_name: str | None = Field(default=None, max_length=100)


class SavingsGoalUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    target_amount: float = Field(gt=0)
    account_name: str | None = Field(default=None, max_length=100)


class SavingsGoalActionResponse(BaseModel):
    id: int
    ok: bool
    message: str
