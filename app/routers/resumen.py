from fastapi import APIRouter

from app.deps import resolve_sheet_id
from app.schemas.resumen import ResumenPeriodoResponse
from app.services.finance_service import get_neto, get_resumen_mes, get_resumen_semana, get_saldos

router = APIRouter(tags=['resumen'])


@router.get('/resumen/{user_id}', response_model=ResumenPeriodoResponse)
def resumen_mes(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_resumen_mes(sheet_id)


@router.get('/resumen/semana/{user_id}', response_model=ResumenPeriodoResponse)
def resumen_semana(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_resumen_semana(sheet_id)


@router.get('/saldos/{user_id}')
def saldos(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_saldos(sheet_id)


@router.get('/neto/{user_id}')
def neto(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_neto(sheet_id)
