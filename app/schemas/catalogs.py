from app.schemas import ResponseModel


class AccountOption(ResponseModel):
    id: int
    name: str
    account_type: str
    currency: str


class CategoryOption(ResponseModel):
    id: int
    name: str
    kind: str


class LoanPersonOption(ResponseModel):
    id: int
    name: str


class CatalogsResponse(ResponseModel):
    user: dict
    accounts: dict
    categories: dict
    loan_people: list[LoanPersonOption]