
from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas.common import MessageResponse
from app.schemas.deudas import DeudasResponse, NuevaDeudaRequest, PagarDeudaRequest
from app.services.deuda_service import create_deuda, list_deudas, list_deudas_activas, pagar_deuda

router = APIRouter(prefix="/deudas", tags=["deudas"])


def resolve_sheet_id(user_id: int) -> str:
    settings = get_settings()
    sheet_id = settings.user_sheets.get(user_id)
    if not sheet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no configurado en USER_SHEETS",
        )
    return sheet_id


@router.get("/{user_id}", response_model=DeudasResponse)
def deudas(user_id: int) -> DeudasResponse:
    sheet_id = resolve_sheet_id(user_id)
    return DeudasResponse(user_id=user_id, spreadsheet_id=sheet_id, deudas=list_deudas(user_id, sheet_id))


@router.get("/activas/{user_id}", response_model=DeudasResponse)
def deudas_activas(user_id: int) -> DeudasResponse:
    sheet_id = resolve_sheet_id(user_id)
    return DeudasResponse(user_id=user_id, spreadsheet_id=sheet_id, deudas=list_deudas_activas(user_id, sheet_id))


@router.post("", response_model=MessageResponse)
def nueva_deuda(payload: NuevaDeudaRequest) -> MessageResponse:
    sheet_id = resolve_sheet_id(payload.user_id)
    result = create_deuda(payload.model_dump(), sheet_id)
    return MessageResponse(message="Nueva deuda recibida", data=result)


@router.post("/pagar", response_model=MessageResponse)
def pagar(payload: PagarDeudaRequest) -> MessageResponse:
    sheet_id = resolve_sheet_id(payload.user_id)
    result = pagar_deuda(payload.model_dump(), sheet_id)
    return MessageResponse(message="Solicitud de pago recibida", data=result)
