import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.debts import (
    DebtCreateRequest,
    DebtCreateResponse,
    DebtPayRequest,
    DebtPayResponse,
    DebtUpdateRequest,
    DebtUpdateResponse,
)
from app.schemas.installment_plans import MigrateDebtRequest, MigrateDebtResponse
from app.services.debt_service import create_debt, pay_debt, update_debt
from app.services.installment_service import migrate_debt_to_tc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["debts"])


@router.post("/deudas", response_model=DebtCreateResponse)
@limiter.limit("20/minute")
def crear_deuda(
    request: Request,
    payload: DebtCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        debt = create_debt(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            creditor=payload.creditor,
            due_date=payload.due_date,
            installment_amount=payload.installment_amount,
            total_installments=payload.total_installments,
            paid_installments=payload.paid_installments,
            payment_frequency=payload.payment_frequency,
        )
        logger.info("Deuda creada: id=%s usuario=%s", debt.id, current_user.telegram_user_id)
        return {"id": int(debt.id), "ok": True, "message": "Deuda creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deudas/pagar", response_model=DebtPayResponse)
@limiter.limit("20/minute")
def pagar_deuda(
    request: Request,
    payload: DebtPayRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        debt = pay_debt(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            debt_id=payload.debt_id,
            payment_date=payload.payment_date,
            payment_method=payload.payment_method,
            account_name=payload.account_name,
            note=payload.note,
        )
        pending = max(debt.total_installments - debt.paid_installments, 0)
        logger.info("Deuda pagada: id=%s cuotas_pagadas=%s usuario=%s", debt.id, debt.paid_installments, current_user.telegram_user_id)
        return {
            "debt_id": int(debt.id),
            "ok": True,
            "message": "Pago registrado correctamente.",
            "paid_installments": int(debt.paid_installments),
            "pending_installments": int(pending),
            "status": debt.status,
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/deudas/{debt_id}", response_model=DebtUpdateResponse)
def editar_deuda(
    debt_id: int,
    payload: DebtUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        debt = update_debt(
            db=db,
            telegram_user_id=current_user.telegram_user_id,
            debt_id=debt_id,
            name=payload.name,
            creditor=payload.creditor,
            due_date=payload.due_date,
            installment_amount=payload.installment_amount,
            total_installments=payload.total_installments,
            payment_frequency=payload.payment_frequency,
        )
        return {"id": int(debt.id), "ok": True, "message": "Deuda actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deudas/{debt_id}/migrate-to-tc", response_model=MigrateDebtResponse)
@limiter.limit("10/minute")
def migrar_deuda_a_tc(
    request: Request,
    debt_id: int,
    payload: MigrateDebtRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    if payload.debt_id != debt_id:
        raise HTTPException(status_code=400, detail="debt_id en URL y payload no coinciden.")
    try:
        result = migrate_debt_to_tc(db, payload)
        logger.info(
            "Deuda migrada a TC: debt_id=%s tipo=%s usuario=%s",
            debt_id, payload.migration_type, current_user.telegram_user_id,
        )
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
