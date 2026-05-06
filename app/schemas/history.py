from pydantic import BaseModel


class HistoryItem(BaseModel):
    id: int
    movement_date: str
    movement_type: str
    subtype: str
    amount: float
    destination_amount: float | None = None

    source_account: str | None = None
    target_account: str | None = None
    transfer_account: str | None = None

    category_name: str | None = None
    loan_person_name: str | None = None
    payment_method: str | None = None
    note: str | None = None

    is_void: bool


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int        # items in this page
    total_count: int  # total matching records (for pagination)