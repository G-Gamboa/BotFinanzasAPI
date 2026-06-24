import logging

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.security.telegram_auth import get_current_telegram_auth

logger = logging.getLogger(__name__)


def get_current_app_user(
    auth=Depends(get_current_telegram_auth),
    db: Session = Depends(get_db),
) -> User:
    telegram_user_id = auth["user"]["id"]
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        logger.warning("Acceso denegado: telegram_user_id=%s no registrado.", telegram_user_id)
        raise HTTPException(status_code=403, detail="Usuario no registrado.")
    if not user.is_active:
        logger.warning("Acceso denegado: telegram_user_id=%s inactivo.", telegram_user_id)
        raise HTTPException(status_code=403, detail="Usuario inactivo.")
    return user


def ensure_same_user(route_telegram_user_id: int, current_user: User):
    if route_telegram_user_id != current_user.telegram_user_id:
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")


def ensure_payload_user(payload_telegram_user_id: int, current_user: User):
    if payload_telegram_user_id != current_user.telegram_user_id:
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")
