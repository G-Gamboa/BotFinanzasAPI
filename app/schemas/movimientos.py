
from pydantic import BaseModel, Field

class MovimientoCreateRequest(BaseModel):
    user_id: int
    tipo: str = Field(..., description="ING, EGR o MOV")
    fecha: str
    categoria: str | None = None
    fuente: str | None = None
    monto: float
    monto_destino: float | None = None
    metodo: str | None = None
    banco: str | None = None
    remitente: str | None = None
    destino: str | None = None
    nota: str | None = None
