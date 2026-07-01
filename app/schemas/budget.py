from pydantic import Field
from app.schemas import ResponseModel


class BudgetCreateRequest(ResponseModel):
    telegram_user_id: int
    category_id: int
    monthly_amount: float = Field(gt=0)


class BudgetUpdateRequest(ResponseModel):
    telegram_user_id: int
    monthly_amount: float = Field(gt=0)


class BudgetItem(ResponseModel):
    id: int
    category_id: int
    category_name: str
    monthly_amount: float
    spent_this_month: float
    pct_used: float          # 0.0 – N (puede superar 1.0 si se excedió)
    remaining: float         # negativo si se excedió
    exceeded_by: float       # 0 si dentro del presupuesto


class BudgetListResponse(ResponseModel):
    items: list[BudgetItem]


class BudgetActionResponse(ResponseModel):
    id: int
    ok: bool
    message: str
