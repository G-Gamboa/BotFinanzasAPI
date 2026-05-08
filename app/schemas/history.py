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
    debt_name: str | None = None
    payment_method: str | None = None
    credit_card_account_id: int | None = None
    credit_card_account_name: str | None = None
    note: str | None = None

    is_void: bool
    record_type: str = "movement"  # 'movement' | 'loan_payment' | 'debt_payment'


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int        # items in this page
    total_count: int  # total matching records (for pagination)
