from typing import Literal
from pydantic import BaseModel, Field, model_validator


MovementType = Literal["ING", "EGR", "MOV"]
PaymentMethod = Literal["Efectivo", "Transferencia"]
MovSubtype = Literal["NORMAL", "AHORRO", "INVERSION", "PRESTAMO"]
MovDirection = Literal[
    "GUARDAR",
    "RETIRAR",
    "INVERTIR",
    "RETIRAR_INV",
    "MOVER_INV",
    "DAR",
    "COBRAR",
    "NORMAL",
]


class MovementCreateRequest(BaseModel):
    telegram_user_id: int
    movement_type: MovementType
    movement_date: str = Field(max_length=10)  # YYYY-MM-DD
    amount: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)

    # ING / EGR
    category_name: str | None = Field(default=None, max_length=100)
    payment_method: PaymentMethod | None = None
    account_name: str | None = Field(default=None, max_length=100)

    # MOV
    mov_subtype: MovSubtype | None = None
    mov_direction: MovDirection | None = None
    source_account_name: str | None = Field(default=None, max_length=100)
    target_account_name: str | None = Field(default=None, max_length=100)
    destination_amount: float | None = Field(default=None, ge=0)

    # préstamos
    loan_person_name: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.movement_type in {"ING", "EGR"}:
            if not self.category_name:
                raise ValueError("category_name es requerido para ING/EGR.")
            if not self.payment_method:
                raise ValueError("payment_method es requerido para ING/EGR.")
            if not self.account_name:
                raise ValueError("account_name es requerido para ING/EGR.")

        if self.movement_type == "MOV":
            if not self.mov_subtype:
                raise ValueError("mov_subtype es requerido para MOV.")
            if not self.mov_direction:
                raise ValueError("mov_direction es requerido para MOV.")

        return self


class MovementCreateResponse(BaseModel):
    id: int
    ok: bool
    message: str