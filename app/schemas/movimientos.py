
from pydantic import BaseModel, Field


class MovimientoRequest(BaseModel):
    user_id: int
    tipo: str = Field(min_length=3)
    fecha: str
    categoria: str | None = None
    fuente: str | None = None
    monto: float = Field(gt=0)
    metodo: str | None = None
    banco: str | None = None
    nota: str | None = None
    remitente: str | None = None
    destino: str | None = None
    bolsa_remitente: str | None = None
    bolsa_destino: str | None = None
    monto_destino: float | None = None
