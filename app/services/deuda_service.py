
from app.schemas.common import MessageResponse
from app.schemas.deudas import DeudaCreateRequest, PagarDeudaRequest

def get_deudas(user_id: int) -> dict:
    return {"user_id": user_id, "items": []}

def get_deudas_activas(user_id: int) -> dict:
    return {"user_id": user_id, "items": []}

def create_deuda(payload: DeudaCreateRequest) -> MessageResponse:
    return MessageResponse(message="Nueva deuda pendiente de implementar", ok=True)

def pagar_deuda(payload: PagarDeudaRequest) -> MessageResponse:
    return MessageResponse(message="Pago de deuda pendiente de implementar", ok=True)
