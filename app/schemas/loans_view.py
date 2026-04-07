from pydantic import BaseModel


class LoanConceptItem(BaseModel):
    concept: str
    balance: float


class LoanPersonItem(BaseModel):
    person: str
    total_balance: float
    concepts: list[LoanConceptItem]


class LoansViewResponse(BaseModel):
    items: list[LoanPersonItem]
    total_people: int