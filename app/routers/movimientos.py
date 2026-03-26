
from fastapi import APIRouter, Depends
from app.auth import require_x_user_id
from app.schemas.common import MessageResponse
from app.schemas.movimientos import MovimientoCreateRequest
from app.services.movimiento_service import create_movimiento

router = APIRouter()

@router.post("/movimientos", response_model=MessageResponse)
def movimientos(payload: MovimientoCreateRequest, _: int = Depends(require_x_user_id)):
    return create_movimiento(payload)
