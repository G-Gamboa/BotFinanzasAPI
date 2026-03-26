from typing import Literal

from pydantic import BaseModel, Field


class MovimientoRequest(BaseModel):
    user_id: int = Field(gt=0)
    tipo: Literal['ING', 'EGR', 'MOV']
    fecha: str
    fuente: str = ''
    categoria: str = ''
    monto: float
    metodo: str = ''
    banco: str = ''
    nota: str = ''
    bolsa_remitente: str = ''
    remitente: str = ''
    bolsa_destino: str = ''
    destino: str = ''
    persona_prestamo: str = ''
    monto_destino: float = 0.0
    mov_type: str = ''
