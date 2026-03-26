
from fastapi import APIRouter, Depends
from app.auth import require_x_user_id
from app.services.finance_service import get_networth, get_saldos

router = APIRouter()

@router.get("/networth/{user_id}")
def networth(user_id: int, _: int = Depends(require_x_user_id)):
    return get_networth(user_id)

@router.get("/saldos/{user_id}")
def saldos(user_id: int, _: int = Depends(require_x_user_id)):
    return get_saldos(user_id)
