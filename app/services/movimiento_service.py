
from app.schemas.common import MessageResponse
from app.schemas.movimientos import MovimientoCreateRequest

def create_movimiento(payload: MovimientoCreateRequest) -> MessageResponse:
    return MessageResponse(message="Movimiento pendiente de implementar", ok=True)
