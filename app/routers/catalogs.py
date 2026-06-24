import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user
from app.schemas.catalogs import CatalogsResponse
from app.schemas.availability import DisponiblesResponse
from app.services.catalog_service import build_catalogs
from app.services.availability_service import build_disponibles

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalogs"])


@router.get("/catalogos/{telegram_user_id}", response_model=CatalogsResponse)
def catalogos(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    settings = get_settings()
    try:
        return build_catalogs(db, telegram_user_id, settings)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/disponibles/{telegram_user_id}", response_model=DisponiblesResponse)
def disponibles(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return build_disponibles(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
