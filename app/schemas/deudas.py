from pydantic import BaseModel, Field


class DeudaItem(BaseModel):
    row: int
    nombre: str
    acreedor: str
    fecha_pago: str
    cuota: float
    meses: int
    pagados: int
    pendientes: int
    saldo: float
    estado: str


class DeudaCreateRequest(BaseModel):
    user_id: int = Field(gt=0)
    deuda_nombre: str
    deuda_acreedor: str
    deuda_fecha_pago: str
    deuda_cuota: float
    deuda_meses: int
    deuda_pagados: int = 0


class DeudaPagarRequest(BaseModel):
    user_id: int = Field(gt=0)
    deuda_row: int = Field(gt=1)
    cuenta_pago: str


class DeudasResponse(BaseModel):
    items: list[DeudaItem]
    total_saldo_activo: float
