
from pydantic import BaseModel, Field


class DeudasResponse(BaseModel):
    user_id: int
    spreadsheet_id: str
    deudas: list[dict]


class NuevaDeudaRequest(BaseModel):
    user_id: int
    deuda_nombre: str = Field(min_length=1)
    deuda_acreedor: str = Field(min_length=1)
    deuda_fecha_pago: str
    deuda_cuota: float = Field(gt=0)
    deuda_meses: int = Field(gt=0)
    deuda_pagados: int = Field(ge=0, default=0)


class PagarDeudaRequest(BaseModel):
    user_id: int
    deuda_row: int = Field(gt=0)
    cuenta_pago: str = Field(min_length=1)
