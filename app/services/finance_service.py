
from app.schemas.resumen import ResumenResponse

def get_resumen(user_id: int) -> ResumenResponse:
    return ResumenResponse(user_id=user_id, ingresos=0.0, egresos=0.0, neto=0.0, moneda="GTQ", detalle=[])

def get_networth(user_id: int) -> dict:
    return {"user_id": user_id, "moneda": "GTQ", "networth": 0.0, "activos": {}, "pasivos": {}}

def get_saldos(user_id: int) -> dict:
    return {"user_id": user_id, "saldos": {}}
