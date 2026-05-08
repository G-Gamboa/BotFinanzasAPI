from typing import Literal
from pydantic import BaseModel, Field

AccountType = Literal["cash", "bank", "investment", "asset", "savings", "loan_pool", "credit_card"]
CurrencyType = Literal["GTQ", "USD"]
CategoryKind = Literal["ING", "EGR"]


class AccountItem(BaseModel):
    id: int
    name: str
    account_type: str
    currency: str
    is_active: bool
    is_system: bool
    sort_order: int
    # Credit card fields (None for non-CC accounts)
    credit_limit: float | None = None
    billing_close_day: int | None = None
    payment_due_day: int | None = None


class AccountListResponse(BaseModel):
    items: list[AccountItem]


class AccountCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    account_type: AccountType
    currency: CurrencyType
    sort_order: int = 0
    credit_limit: float | None = Field(default=None, gt=0)
    billing_close_day: int | None = Field(default=None, ge=1, le=28)
    payment_due_day: int | None = Field(default=None, ge=1, le=28)


class AccountUpdateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    account_type: AccountType
    currency: CurrencyType
    sort_order: int = 0
    credit_limit: float | None = Field(default=None, gt=0)
    billing_close_day: int | None = Field(default=None, ge=1, le=28)
    payment_due_day: int | None = Field(default=None, ge=1, le=28)


class AccountActionResponse(BaseModel):
    id: int
    ok: bool
    message: str


class CategoryItem(BaseModel):
    id: int
    name: str
    kind: str
    is_active: bool
    is_system: bool
    sort_order: int


class CategoryListResponse(BaseModel):
    items: list[CategoryItem]


class CategoryCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    kind: CategoryKind
    sort_order: int = 0


class CategoryUpdateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    kind: CategoryKind
    sort_order: int = 0


class CategoryActionResponse(BaseModel):
    id: int
    ok: bool
    message: str


class LoanPersonItem(BaseModel):
    id: int
    name: str
    is_active: bool


class LoanPersonListResponse(BaseModel):
    items: list[LoanPersonItem]


class LoanPersonCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)


class LoanPersonUpdateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)


class LoanPersonActionResponse(BaseModel):
    id: int
    ok: bool
    message: str