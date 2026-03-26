from fastapi import APIRouter, HTTPException, status

from app.deps import resolve_sheet_id
from app.schemas.common import MessageResponse
from app.schemas.deudas import DeudaCreateRequest, DeudaPagarRequest, DeudasResponse
from app.services.deuda_service import create_deuda, pagar_deuda
from app.services.finance_service import get_deudas, get_total_deudas

router = APIRouter(prefix='/deudas', tags=['deudas'])


@router.get('/{user_id}', response_model=DeudasResponse)
def deudas(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    items = get_deudas(sheet_id)
    return DeudasResponse(items=items, total_saldo_activo=get_total_deudas(sheet_id))


@router.get('/activas/{user_id}', response_model=DeudasResponse)
def deudas_activas(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    items = [d for d in get_deudas(sheet_id) if d['estado'].lower() == 'activa' and d['pendientes'] > 0]
    total = round(sum(d['saldo'] for d in items), 2)
    return DeudasResponse(items=items, total_saldo_activo=total)


@router.post('', response_model=MessageResponse)
def nueva_deuda(payload: DeudaCreateRequest):
    sheet_id = resolve_sheet_id(payload.user_id)
    try:
        result = create_deuda(payload.model_dump(), sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message='Deuda guardada', data=result)


@router.post('/pagar', response_model=MessageResponse)
def registrar_pago(payload: DeudaPagarRequest):
    sheet_id = resolve_sheet_id(payload.user_id)
    try:
        result = pagar_deuda(payload.deuda_row, payload.cuenta_pago, sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message='Pago registrado', data=result)
