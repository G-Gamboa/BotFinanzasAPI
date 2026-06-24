import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user
from app.schemas.history import HistoryResponse
from app.schemas.loans_view import LoansViewResponse
from app.services.history_service import build_history
from app.services.loans_view_service import build_loans_view

logger = logging.getLogger(__name__)
router = APIRouter(tags=["history"])


@router.get("/historial/{telegram_user_id}", response_model=HistoryResponse)
def historial(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    category_name: str | None = None,
    payment_method: str | None = None,
    note: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(0, offset)
        return build_history(
            db,
            telegram_user_id,
            date_from=date_from,
            date_to=date_to,
            movement_type=movement_type,
            category_name=category_name,
            payment_method=payment_method,
            note=note,
            amount_min=amount_min,
            amount_max=amount_max,
            limit=safe_limit,
            offset=safe_offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/prestamos/{telegram_user_id}", response_model=LoansViewResponse)
def prestamos_view(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return build_loans_view(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
