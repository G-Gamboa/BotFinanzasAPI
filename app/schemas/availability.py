from app.schemas import ResponseModel


class CuentaDisponibleItem(ResponseModel):
    cuenta: str
    saldo: float


class PrestamoDisponibleItem(ResponseModel):
    persona: str
    saldo: float


class DisponiblesResponse(ResponseModel):
    saldos_liquidos: list[CuentaDisponibleItem]
    ahorro_por_cuenta: list[CuentaDisponibleItem]
    prestamos_por_persona: list[PrestamoDisponibleItem]