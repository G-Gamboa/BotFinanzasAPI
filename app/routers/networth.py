from fastapi import APIRouter

from app.deps import resolve_sheet_id
from app.schemas.networth import NetworthResponse
from app.services.finance_service import get_networth

router = APIRouter(tags=['networth'])


@router.get('/networth/{user_id}', response_model=NetworthResponse)
def networth(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_networth(sheet_id)
