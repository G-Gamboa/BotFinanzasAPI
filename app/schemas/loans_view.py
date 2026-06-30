from app.schemas import ResponseModel


class LoanConceptItem(ResponseModel):
    concept: str
    balance: float
    is_tc_loan: bool = False
    tc_account_name: str | None = None


class LoanPersonItem(ResponseModel):
    person: str
    total_balance: float
    concepts: list[LoanConceptItem]


class LoansViewResponse(ResponseModel):
    items: list[LoanPersonItem]
    total_people: int