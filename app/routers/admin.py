import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_db
from app.db.models import User, UserSetting
from app.limiter import limiter
from app.routers.finance import get_current_app_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class AdminCreateUserRequest(BaseModel):
    telegram_user_id: int
    first_name: str | None = Field(default=None, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)
    username: str | None = Field(default=None, max_length=150)
    can_use_loans: bool = False


class AdminCreateUserResponse(BaseModel):
    id: int
    ok: bool
    message: str
    telegram_user_id: int


def require_admin(current_user: User = Depends(get_current_app_user)) -> User:
    settings = get_settings()
    if current_user.telegram_user_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Solo administradores pueden usar este endpoint.")
    return current_user


@router.post("/usuarios", response_model=AdminCreateUserResponse)
@limiter.limit("10/minute")
def crear_usuario(
    request: Request,
    payload: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = db.scalar(
        select(User).where(User.telegram_user_id == payload.telegram_user_id)
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un usuario con telegram_user_id {payload.telegram_user_id}.",
        )

    user = User(
        telegram_user_id=payload.telegram_user_id,
        first_name=payload.first_name or None,
        last_name=payload.last_name or None,
        username=payload.username or None,
        is_active=True,
        can_use_loans=payload.can_use_loans,
        theme_key="neutral",
    )
    db.add(user)
    db.flush()

    setting = UserSetting(
        user_id=user.id,
        show_amounts_default=False,
        default_tab="movimientos",
    )
    db.add(setting)
    db.commit()
    db.refresh(user)

    logger.info(
        "Admin %s creó usuario telegram_user_id=%s (id=%s)",
        admin.telegram_user_id, user.telegram_user_id, user.id,
    )
    return {
        "id": int(user.id),
        "ok": True,
        "message": f"Usuario creado correctamente (ID interno: {user.id}).",
        "telegram_user_id": int(user.telegram_user_id),
    }
