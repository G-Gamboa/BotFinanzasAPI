import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.vault import (
    VaultConfigResponse,
    VaultSetupRequest,
    VaultItemsResponse,
    VaultItemCreateRequest,
    VaultItemUpdateRequest,
    VaultActionResponse,
)
from app.services.vault_service import (
    get_vault_config,
    setup_vault,
    update_vault_config,
    list_vault_items,
    create_vault_item,
    update_vault_item,
    delete_vault_item,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vault"])


@router.get("/vault/config/{telegram_user_id}", response_model=VaultConfigResponse)
def get_config(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    config = get_vault_config(db, telegram_user_id)
    if not config:
        raise HTTPException(status_code=404, detail="Bóveda no configurada.")
    return {"salt": config.salt, "dek_wrapped": config.dek_wrapped}


@router.post("/vault/config", response_model=VaultActionResponse)
@limiter.limit("10/minute")
def post_config(
    request: Request,
    payload: VaultSetupRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        config = setup_vault(db, payload.telegram_user_id, payload.salt, payload.dek_wrapped)
        logger.info("Vault configurado: user=%s", current_user.telegram_user_id)
        return {"id": int(config.id), "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/vault/config", response_model=VaultActionResponse)
@limiter.limit("10/minute")
def patch_config(
    request: Request,
    payload: VaultSetupRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        config = update_vault_config(db, payload.telegram_user_id, payload.salt, payload.dek_wrapped)
        logger.info("Vault contraseña cambiada: user=%s", current_user.telegram_user_id)
        return {"id": int(config.id), "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/vault/items/{telegram_user_id}", response_model=VaultItemsResponse)
def get_items(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    items = list_vault_items(db, telegram_user_id)
    return {
        "items": [
            {"id": int(i.id), "ciphertext": i.ciphertext, "updated_at": i.updated_at}
            for i in items
        ]
    }


@router.post("/vault/items", response_model=VaultActionResponse)
def post_item(
    payload: VaultItemCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        item = create_vault_item(db, payload.telegram_user_id, payload.ciphertext)
        return {"id": int(item.id), "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/vault/items/{item_id}", response_model=VaultActionResponse)
def put_item(
    item_id: int,
    payload: VaultItemUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        item = update_vault_item(db, item_id, payload.telegram_user_id, payload.ciphertext)
        return {"id": int(item.id), "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/vault/items/{item_id}", response_model=VaultActionResponse)
def del_item(
    item_id: int,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        delete_vault_item(db, item_id, telegram_user_id)
        return {"id": item_id, "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
