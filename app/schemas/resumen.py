
from pydantic import BaseModel, Field

class ResumenLinea(BaseModel):
    categoria: str
    monto: float

class ResumenResponse(BaseModel):
    user_id: int
    ingresos: float
    egresos: float
    neto: float
    moneda: str = "GTQ"
    detalle: list[ResumenLinea] = Field(default_factory=list)
