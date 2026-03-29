from pydantic import BaseModel


class AccountOption(BaseModel):
    id: int
    name: str
    account_type: str
    currency: str


class CategoryOption(BaseModel):
    id: int
    name: str
    kind: str


class LoanPersonOption(BaseModel):
    id: int
    name: str


class CatalogsResponse(BaseModel):
    user: dict
    accounts: dict
    categories: dict
    loan_people: list[LoanPersonOption]