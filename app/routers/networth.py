
from fastapi import APIRouter, Depends

from app.deps import get_user_sheet_id
from app.schemas.networth import NetworthResponse
from app.services.finance_service import get_networth

router = APIRouter(prefix="/networth", tags=["networth"])


@router.get("/{user_id}", response_model=NetworthResponse)
def networth(user_id: int, sheet_id: str = Depends(get_user_sheet_id)) -> NetworthResponse:
    return NetworthResponse(user_id=user_id, spreadsheet_id=sheet_id, networth=get_networth(user_id, sheet_id))
