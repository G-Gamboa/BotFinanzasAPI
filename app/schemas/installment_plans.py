from datetime import date
from pydantic import BaseModel, Field


class InstallmentPlanItem(BaseModel):
    id: int
    credit_card_account_id: int
    credit_card_name: str
    name: str
    total_amount: float
    total_installments: int
    monthly_amount: float
    paid_installments: int
    pending_installments: int
    purchase_date: str
    first_charge_date: str
    next_charge_date: str | None
    remaining_amount: float
    status: str
    note: str | None = None
    is_loan: bool = False
    loan_person_id: int | None = None
    loan_person_name: str | None = None
    category_id: int | None = None
    category_name: str | None = None


class InstallmentPlansResponse(BaseModel):
    items: list[InstallmentPlanItem]


class InstallmentPlanCreateRequest(BaseModel):
    telegram_user_id: int
    credit_card_account_id: int
    name: str = Field(min_length=1, max_length=150)
    total_amount: float = Field(gt=0)
    total_installments: int = Field(ge=2)
    monthly_amount: float = Field(gt=0)
    purchase_date: str = Field(max_length=10)   # YYYY-MM-DD
    first_charge_date: str = Field(max_length=10)
    note: str | None = Field(default=None, max_length=500)
    is_loan: bool = False
    loan_person_id: int | None = None
    category_id: int | None = None


class InstallmentPlanUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    note: str | None = Field(default=None, max_length=500)
    category_id: int | None = None


class InstallmentPlanActionResponse(BaseModel):
    id: int
    ok: bool
    message: str


class PendingChargeItem(BaseModel):
    plan_id: int
    plan_name: str
    amount: float
    charge_date: str
    credit_card_name: str


class ProcessPendingResponse(BaseModel):
    created: list[PendingChargeItem]
    total_created: int


class MigrateDebtRequest(BaseModel):
    telegram_user_id: int
    debt_id: int
    credit_card_account_id: int
    # 'normal' = cargo único por saldo restante | 'visacuota' = mantiene el plan
    migration_type: str
    # Solo para migration_type='visacuota': primer corte donde aparece
    first_charge_date: str | None = Field(default=None, max_length=10)


class MigrateDebtResponse(BaseModel):
    ok: bool
    message: str
    remaining_amount: float
    pending_installments: int
