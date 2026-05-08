from typing import Literal
from pydantic import BaseModel, Field

AccountType = Literal["cash", "bank", "investment", "asset", "savings", "loan_pool"]
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


class AccountListResponse(BaseModel):
    items: list[AccountItem]


class AccountCreateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    account_type: AccountType
    currency: CurrencyType
    sort_order: int = 0


class AccountUpdateRequest(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=100)
    account_type: AccountType
    currency: CurrencyType
    sort_order: int = 0


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