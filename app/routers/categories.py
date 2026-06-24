import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.configuration import (
    CategoryListResponse,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CategoryActionResponse,
)
from app.services.configuration_service import (
    list_categories,
    create_category,
    update_category,
    set_category_active,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["categories"])


@router.get("/categorias/{telegram_user_id}", response_model=CategoryListResponse)
def categorias(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return list_categories(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/categorias", response_model=CategoryActionResponse)
@limiter.limit("20/minute")
def crear_categoria(
    request: Request,
    payload: CategoryCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        category = create_category(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {"id": int(category.id), "ok": True, "message": "Categoría creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}", response_model=CategoryActionResponse)
def editar_categoria(
    category_id: int,
    payload: CategoryUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        category = update_category(
            db=db,
            category_id=category_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {"id": int(category.id), "ok": True, "message": "Categoría actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/activar", response_model=CategoryActionResponse)
def activar_categoria(
    category_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        category = set_category_active(db, category_id, current_user.telegram_user_id, True)
        return {"id": int(category.id), "ok": True, "message": "Categoría activada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/desactivar", response_model=CategoryActionResponse)
def desactivar_categoria(
    category_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        category = set_category_active(db, category_id, current_user.telegram_user_id, False)
        return {"id": int(category.id), "ok": True, "message": "Categoría desactivada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
