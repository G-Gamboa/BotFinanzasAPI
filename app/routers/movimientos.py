
from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas.common import MessageResponse
from app.schemas.movimientos import MovimientoRequest
from app.services.movimiento_service import create_movimiento

router = APIRouter(prefix="/movimientos", tags=["movimientos"])


def resolve_sheet_id(user_id: int) -> str:
    settings = get_settings()
    sheet_id = settings.user_sheets.get(user_id)
    if not sheet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no configurado en USER_SHEETS",
        )
    return sheet_id


@router.post("", response_model=MessageResponse)
def nuevo_movimiento(payload: MovimientoRequest) -> MessageResponse:
    sheet_id = resolve_sheet_id(payload.user_id)
    result = create_movimiento(payload.model_dump(), sheet_id)
    return MessageResponse(message="Movimiento recibido", data=result)
