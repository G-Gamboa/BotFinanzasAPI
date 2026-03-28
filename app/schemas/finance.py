from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool


class SaldoItem(BaseModel):
    cuenta: str
    saldo: float


class NetworthResponse(BaseModel):
    liquid_map: dict[str, float]
    liquidez_gtq: float
    ahorro_map: dict[str, float]
    ahorro_gtq: float
    prestamos_map: dict[str, float]
    prestamos_gtq: float
    inv_map: dict[str, float]
    inv_total_usd: float
    total_gtq: float
    tc: float


class NetoResponse(BaseModel):
    patrimonio_bruto: float
    pasivos: float
    patrimonio_neto: float
