
from fastapi import APIRouter, Depends

from app.deps import get_user_sheet_id
from app.schemas.resumen import ResumenResponse
from app.services.finance_service import get_resumen, get_saldos

router = APIRouter(prefix="/resumen", tags=["resumen"])
saldos_router = APIRouter(prefix="/saldos", tags=["saldos"])


@router.get("/{user_id}", response_model=ResumenResponse)
def resumen(user_id: int, sheet_id: str = Depends(get_user_sheet_id)) -> ResumenResponse:
    return ResumenResponse(user_id=user_id, spreadsheet_id=sheet_id, resumen=get_resumen(user_id, sheet_id))


@saldos_router.get("/{user_id}")
def saldos(user_id: int, sheet_id: str = Depends(get_user_sheet_id)) -> dict:
    return {"user_id": user_id, "spreadsheet_id": sheet_id, "saldos": get_saldos(user_id, sheet_id)}
