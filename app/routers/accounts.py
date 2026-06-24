import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.configuration import (
    AccountListResponse,
    AccountCreateRequest,
    AccountUpdateRequest,
    AccountActionResponse,
)
from app.services.configuration_service import (
    list_accounts,
    create_account,
    update_account,
    set_account_active,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["accounts"])


@router.get("/cuentas/{telegram_user_id}", response_model=AccountListResponse)
def cuentas(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return list_accounts(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/cuentas", response_model=AccountActionResponse)
@limiter.limit("20/minute")
def crear_cuenta(
    request: Request,
    payload: AccountCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        account = create_account(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            account_type=payload.account_type,
            currency=payload.currency,
            sort_order=payload.sort_order,
            credit_limit=payload.credit_limit,
            billing_close_day=payload.billing_close_day,
            payment_due_day=payload.payment_due_day,
            tc_type=payload.tc_type,
            tc_exchange_rate=payload.tc_exchange_rate,
            visacuotas_limit=payload.visacuotas_limit,
        )
        return {"id": int(account.id), "ok": True, "message": "Cuenta creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}", response_model=AccountActionResponse)
def editar_cuenta(
    account_id: int,
    payload: AccountUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        account = update_account(
            db=db,
            account_id=account_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            account_type=payload.account_type,
            currency=payload.currency,
            sort_order=payload.sort_order,
            credit_limit=payload.credit_limit,
            billing_close_day=payload.billing_close_day,
            payment_due_day=payload.payment_due_day,
            tc_type=payload.tc_type,
            tc_exchange_rate=payload.tc_exchange_rate,
            visacuotas_limit=payload.visacuotas_limit,
        )
        return {"id": int(account.id), "ok": True, "message": "Cuenta actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/activar", response_model=AccountActionResponse)
def activar_cuenta(
    account_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        account = set_account_active(db, account_id, current_user.telegram_user_id, True)
        return {"id": int(account.id), "ok": True, "message": "Cuenta activada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/desactivar", response_model=AccountActionResponse)
def desactivar_cuenta(
    account_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        account = set_account_active(db, account_id, current_user.telegram_user_id, False)
        return {"id": int(account.id), "ok": True, "message": "Cuenta desactivada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
