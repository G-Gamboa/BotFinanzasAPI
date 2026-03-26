
from pydantic import BaseModel

class DeudaCreateRequest(BaseModel):
    user_id: int
    deuda_nombre: str
    deuda_acreedor: str
    deuda_fecha_pago: str
    deuda_cuota: float
    deuda_meses: int
    deuda_pagados: int = 0

class PagarDeudaRequest(BaseModel):
    user_id: int
    deuda_row: int
    cuenta_pago: str
