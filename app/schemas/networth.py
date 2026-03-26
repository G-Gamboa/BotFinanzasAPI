from pydantic import BaseModel


class NetworthResponse(BaseModel):
    liquido_q: dict[str, float]
    ahorro_q: dict[str, float]
    prestamos_q: dict[str, float]
    inversiones_usd: dict[str, float]
    total_liquido_q: float
    total_ahorro_q: float
    total_prestamos_q: float
    total_inversiones_usd: float
    total_inversiones_q: float
    networth_q: float
    usd_to_gtq: float
