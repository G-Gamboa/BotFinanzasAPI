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


class AdminUserItem(BaseModel):
    id: int
    telegram_user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    is_active: bool
    can_use_loans: bool


class AdminUsersResponse(BaseModel):
    items: list[AdminUserItem]


class AdminToggleUserRequest(BaseModel):
    is_active: bool


def require_admin(current_user: User = Depends(get_current_app_user)) -> User:
    settings = get_settings()
    if current_user.telegram_user_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Solo administradores pueden usar este endpoint.")
    return current_user


@router.get("/usuarios", response_model=AdminUsersResponse)
def listar_usuarios(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.scalars(select(User).order_by(User.id)).all()
    return {
        "items": [
            {
                "id": int(u.id),
                "telegram_user_id": int(u.telegram_user_id),
                "first_name": u.first_name,
                "last_name": u.last_name,
                "username": u.username,
                "is_active": u.is_active,
                "can_use_loans": u.can_use_loans,
            }
            for u in users
        ]
    }


@router.patch("/usuarios/{user_id}", response_model=AdminCreateUserResponse)
def toggle_usuario(
    user_id: int,
    payload: AdminToggleUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.telegram_user_id == admin.telegram_user_id:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo.")

    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)

    action = "activado" if payload.is_active else "desactivado"
    logger.info("Admin %s %s usuario id=%s", admin.telegram_user_id, action, user.id)
    return {
        "id": int(user.id),
        "ok": True,
        "message": f"Usuario {action} correctamente.",
        "telegram_user_id": int(user.telegram_user_id),
    }


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
