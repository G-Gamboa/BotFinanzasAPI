from pydantic import BaseModel, Field, model_validator


class DebtCreateRequest(BaseModel):
    telegram_user_id: int
    name: str
    creditor: str
    due_date: str  # YYYY-MM-DD
    installment_amount: float = Field(gt=0)
    total_installments: int = Field(gt=0)
    paid_installments: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_paid_vs_total(self):
        if self.paid_installments > self.total_installments:
            raise ValueError("paid_installments no puede ser mayor que total_installments.")
        return self


class DebtCreateResponse(BaseModel):
    id: int
    ok: bool
    message: str


class DebtPayRequest(BaseModel):
    telegram_user_id: int
    debt_id: int
    payment_date: str  # YYYY-MM-DD
    payment_method: str
    account_name: str
    note: str | None = None


class DebtPayResponse(BaseModel):
    debt_id: int
    ok: bool
    message: str
    paid_installments: int
    pending_installments: int
    status: str