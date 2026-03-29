from pydantic import BaseModel


class CuentaDisponibleItem(BaseModel):
    cuenta: str
    saldo: float


class PrestamoDisponibleItem(BaseModel):
    persona: str
    saldo: float


class DisponiblesResponse(BaseModel):
    saldos_liquidos: list[CuentaDisponibleItem]
    ahorro_por_cuenta: list[CuentaDisponibleItem]
    prestamos_por_persona: list[PrestamoDisponibleItem]