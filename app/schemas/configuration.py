from typing import Literal
from pydantic import BaseModel, Field

AccountType = Literal["cash", "bank", "investment", "asset"]
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