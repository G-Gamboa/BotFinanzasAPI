from fastapi import APIRouter, HTTPException, status

from app.deps import resolve_sheet_id
from app.schemas.common import MessageResponse
from app.schemas.movimientos import MovimientoRequest
from app.services.movimiento_service import create_movimiento

router = APIRouter(prefix='/movimientos', tags=['movimientos'])


@router.post('', response_model=MessageResponse)
def nuevo_movimiento(payload: MovimientoRequest):
    sheet_id = resolve_sheet_id(payload.user_id)
    try:
        result = create_movimiento(payload.model_dump(), sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message='Movimiento guardado', data=result)
