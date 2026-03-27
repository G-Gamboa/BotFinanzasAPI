from fastapi import APIRouter, HTTPException, status

from app.deps import resolve_sheet_id
from app.schemas.common import MessageResponse
from app.schemas.movimientos import MovimientoRequest
from app.services.movimiento_service import create_movimiento
router = APIRouter(prefix="/movimientos", tags=["movimientos"])

from app.config import get_settings


@router.post("")
def crear_movimiento(payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id es requerido.")

    settings = get_settings()
    sheet_id = settings.user_sheets_map.get(str(user_id))
    if not sheet_id:
        raise HTTPException(status_code=404, detail="Usuario no configurado.")

    try:
        return create_movimiento(payload, sheet_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post('', response_model=MessageResponse)
def nuevo_movimiento(payload: MovimientoRequest):
    sheet_id = resolve_sheet_id(payload.user_id)
    try:
        result = create_movimiento(payload.model_dump(), sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message='Movimiento guardado', data=result)
