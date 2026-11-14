from typing import Literal

from pydantic import BaseModel, Field

ItemKind = Literal["ingreso", "pago", "abono", "cargo_tc", "recordatorio"]
Recurrence = Literal["none", "weekly", "biweekly", "monthly"]
Currency = Literal["GTQ", "USD"]
PayMethod = Literal["cash", "transfer", "credit_card"]


class ScheduledItemCreate(BaseModel):
    telegram_user_id: int
    kind: ItemKind
    concept: str = Field(min_length=1, max_length=120)
    amount: float | None = Field(default=None, gt=0)
    currency: Currency = "GTQ"
    start_date: str | None = Field(default=None, max_length=10)
    recurrence: Recurrence = "none"
    end_date: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)
    account_name: str | None = Field(default=None, max_length=100)
    category_name: str | None = Field(default=None, max_length=100)
    payment_method: PayMethod | None = None
    credit_card_account_id: int | None = None


class ScheduledItemUpdate(BaseModel):
    telegram_user_id: int
    concept: str | None = Field(default=None, max_length=120)
    amount: float | None = Field(default=None, gt=0)
    currency: Currency | None = None
    start_date: str | None = Field(default=None, max_length=10)
    recurrence: Recurrence | None = None
    end_date: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)
    account_name: str | None = Field(default=None, max_length=100)
    category_name: str | None = Field(default=None, max_length=100)
    payment_method: PayMethod | None = None
    credit_card_account_id: int | None = None


class OccurrenceUpdate(BaseModel):
    telegram_user_id: int
    item_id: int
    due_date: str | None = Field(default=None, max_length=10)
    amount: float | None = Field(default=None, gt=0)
    skip: bool | None = None
    undo: bool = False


class ConfirmScheduled(BaseModel):
    telegram_user_id: int
    item_id: int
    due_date: str | None = Field(default=None, max_length=10)
    payment_date: str = Field(max_length=10)
    amount: float | None = Field(default=None, gt=0)
    # Solo abonos en dólares: quetzales que salieron de la cuenta
    amount_gtq: float | None = Field(default=None, gt=0)
    account_name: str | None = Field(default=None, max_length=100)
    category_name: str | None = Field(default=None, max_length=100)
    payment_method: PayMethod | None = None
    credit_card_account_id: int | None = None
    note: str | None = Field(default=None, max_length=300)


class ConfirmDebt(BaseModel):
    telegram_user_id: int
    debt_id: int
    payment_date: str = Field(max_length=10)
    account_name: str | None = Field(default=None, max_length=100)
    payment_method: PayMethod | None = None
    note: str | None = Field(default=None, max_length=300)


class NoteCreate(BaseModel):
    telegram_user_id: int
    text: str = Field(min_length=1, max_length=300)
