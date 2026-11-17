from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

PaymentFrequency = Literal["weekly", "biweekly", "monthly", "none"]


def _blank_to_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _require_date_if_periodic(due_date: str | None, frequency: str) -> None:
    # Solo una deuda "sin fecha fija" puede quedar sin fecha
    if due_date is None and frequency != "none":
        raise ValueError("Pon la fecha del próximo pago, o marca la deuda como sin fecha fija.")


class DebtCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=150)
    creditor: str = Field(min_length=1, max_length=150)
    due_date: str | None = Field(default=None, max_length=10)  # YYYY-MM-DD; vacía = sin fecha
    installment_amount: float = Field(gt=0)
    total_installments: int = Field(gt=0)
    paid_installments: int = Field(ge=0)
    payment_frequency: PaymentFrequency = "monthly"
    payment_account_name: str | None = Field(default=None, max_length=100)

    @field_validator("due_date", mode="before")
    @classmethod
    def blank_date(cls, value):
        return _blank_to_none(value)

    @model_validator(mode="after")
    def validate_paid_vs_total(self):
        if self.paid_installments > self.total_installments:
            raise ValueError("paid_installments no puede ser mayor que total_installments.")
        _require_date_if_periodic(self.due_date, self.payment_frequency)
        return self


class DebtCreateResponse(BaseModel):
    id: int
    ok: bool
    message: str


class DebtPayRequest(BaseModel):
    telegram_user_id: int
    debt_id: int
    payment_date: str = Field(max_length=10)  # YYYY-MM-DD
    payment_method: str = Field(max_length=30)
    account_name: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class DebtPayResponse(BaseModel):
    debt_id: int
    ok: bool
    message: str
    paid_installments: int
    pending_installments: int
    status: str


class DebtUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    creditor: str = Field(min_length=1, max_length=150)
    due_date: str | None = Field(default=None, max_length=10)
    installment_amount: float = Field(gt=0)
    total_installments: int = Field(gt=0)
    payment_frequency: PaymentFrequency = "monthly"
    payment_account_name: str | None = Field(default=None, max_length=100)

    @field_validator("due_date", mode="before")
    @classmethod
    def blank_date(cls, value):
        return _blank_to_none(value)

    @model_validator(mode="after")
    def validate_date(self):
        _require_date_if_periodic(self.due_date, self.payment_frequency)
        return self


class DebtUpdateResponse(BaseModel):
    id: int
    ok: bool
    message: str
