import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.schemas.preferences import PreferencesResponse, PreferencesUpdateRequest, PreferencesUpdateResponse
from app.services.preferences_service import get_preferences, update_preferences

logger = logging.getLogger(__name__)
router = APIRouter(tags=["preferences"])


@router.get("/preferencias/{telegram_user_id}", response_model=PreferencesResponse)
def preferencias(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return get_preferences(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/preferencias", response_model=PreferencesUpdateResponse)
def actualizar_preferencias(
    payload: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        update_preferences(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            show_amounts_default=payload.show_amounts_default,
            default_tab=payload.default_tab,
            usd_to_gtq=payload.usd_to_gtq,
            theme_key=payload.theme_key,
            tab_order=payload.tab_order,
        )
        return {"ok": True, "message": "Preferencias actualizadas correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
