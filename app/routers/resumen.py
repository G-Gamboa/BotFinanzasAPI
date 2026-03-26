
from fastapi import APIRouter, Depends
from app.auth import require_x_user_id
from app.schemas.resumen import ResumenResponse
from app.services.finance_service import get_resumen

router = APIRouter()

@router.get("/resumen/{user_id}", response_model=ResumenResponse)
def resumen(user_id: int, _: int = Depends(require_x_user_id)):
    return get_resumen(user_id)
