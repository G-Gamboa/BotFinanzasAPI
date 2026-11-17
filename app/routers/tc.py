import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.finance import CreditCardBalancesResponse
from app.schemas.transactions import (
    CreditCardPaymentRequest,
    CreditCardPaymentResponse,
    CreditCardVoidRequest,
)
from app.schemas.installment_plans import (
    InstallmentPlansResponse,
    InstallmentPlanCreateRequest,
    InstallmentPlanUpdateRequest,
    InstallmentPlanActionResponse,
    ProcessPendingResponse,
)
from pydantic import BaseModel, Field

import base64
import binascii

from app.services.bi_statement_parser import StatementError, parse_bi_statement
from app.services.card_statement_service import clear_statement, set_statement
from app.services.statement_reconcile_service import reconcile
from app.services.finance_db_service import build_cc_balances
from app.services.transaction_service import create_tc_payment, void_tc_payment
from app.ws.manager import manager
from app.services.installment_service import (
    list_installment_plans,
    create_installment_plan,
    update_installment_plan,
    delete_installment_plan,
    process_pending_charges,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tc"])


@router.get("/tc-balances/{telegram_user_id}", response_model=CreditCardBalancesResponse)
def get_tc_balances(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    items = build_cc_balances(db, telegram_user_id)
    return {"items": items}


class StatementRequest(BaseModel):
    telegram_user_id: int
    amount_q: float | None = Field(default=None, ge=0, le=10_000_000)
    amount_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    reset: bool = False  # volver al contado calculado


@router.post("/tc/{card_id}/contado")
def ajustar_contado(
    card_id: int,
    payload: StatementRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        if payload.reset:
            clear_statement(db, payload.telegram_user_id, card_id)
            message = "Volviste al pago de contado calculado."
        else:
            set_statement(db, payload.telegram_user_id, card_id, payload.amount_q, payload.amount_usd)
            message = "Pago de contado ajustado para este corte."
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"ok": True, "message": message}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


MAX_STATEMENT_BYTES = 5 * 1024 * 1024


class StatementUploadRequest(BaseModel):
    telegram_user_id: int
    pdf_base64: str = Field(min_length=10, max_length=7_000_000)


@router.post("/tc/{card_id}/estado-cuenta")
@limiter.limit("10/minute")
def revisar_estado_cuenta(
    request: Request,
    card_id: int,
    payload: StatementUploadRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    """Lee el PDF del banco en memoria y lo compara con la app. No guarda el archivo ni sus datos."""
    ensure_payload_user(payload.telegram_user_id, current_user)
    raw = payload.pdf_base64.split(",", 1)[-1]
    try:
        pdf = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="El archivo no llegó completo. Vuelve a subirlo.")
    if len(pdf) > MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=400, detail="El PDF pesa más de 5 MB.")
    if not pdf.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="El archivo no es un PDF.")
    try:
        statement = parse_bi_statement(pdf)
        result = reconcile(db, payload.telegram_user_id, card_id, statement)
    except (StatementError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        del pdf
    logger.info("Estado de cuenta revisado user=%s card=%s lineas=%s",
                current_user.telegram_user_id, card_id, result["statement"]["lines"])
    return result


@router.post("/tc-payments", response_model=CreditCardPaymentResponse)
@limiter.limit("30/minute")
def abonar_tc(
    request: Request,
    payload: CreditCardPaymentRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        payment = create_tc_payment(db, payload)
        logger.info(
            "TC payment id=%s user=%s tc_account=%s amount=%s",
            payment.id, current_user.telegram_user_id, payload.credit_card_account_id, payload.amount,
        )
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"id": int(payment.id), "ok": True, "message": "Abono registrado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/tc-payments/{payment_id}/anular", response_model=CreditCardPaymentResponse)
def anular_tc_payment(
    payment_id: int,
    payload: CreditCardVoidRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        payment = void_tc_payment(db, payload.telegram_user_id, payment_id, payload.reason)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"id": int(payment.id), "ok": True, "message": "Abono anulado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/cc-installment-plans/{telegram_user_id}", response_model=InstallmentPlansResponse)
def get_installment_plans(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        items = list_installment_plans(db, telegram_user_id)
        return {"items": items}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/cc-installment-plans", response_model=InstallmentPlanActionResponse)
@limiter.limit("20/minute")
def crear_installment_plan(
    request: Request,
    payload: InstallmentPlanCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        plan = create_installment_plan(db, payload)
        logger.info("Plan de cuotas creado: id=%s usuario=%s", plan.id, current_user.telegram_user_id)
        return {"id": int(plan.id), "ok": True, "message": "Plan de cuotas creado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cc-installment-plans/{plan_id}", response_model=InstallmentPlanActionResponse)
def editar_installment_plan(
    plan_id: int,
    payload: InstallmentPlanUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        plan = update_installment_plan(
            db=db,
            plan_id=plan_id,
            telegram_user_id=current_user.telegram_user_id,
            name=payload.name,
            note=payload.note,
            category_id=payload.category_id,
        )
        return {"id": int(plan.id), "ok": True, "message": "Plan de cuotas actualizado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/cc-installment-plans/{plan_id}", response_model=InstallmentPlanActionResponse)
def eliminar_installment_plan(
    plan_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        plan = delete_installment_plan(
            db=db,
            plan_id=plan_id,
            telegram_user_id=current_user.telegram_user_id,
        )
        return {"id": int(plan.id), "ok": True, "message": "Plan de cuotas cancelado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/cc-installment-plans/process-pending/{telegram_user_id}",
    response_model=ProcessPendingResponse,
)
@limiter.limit("10/minute")
def procesar_cargos_pendientes(
    request: Request,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        created = process_pending_charges(db, telegram_user_id)
        if created:
            logger.info(
                "Cargos de visacuotas generados: %s movimientos para usuario=%s",
                len(created), current_user.telegram_user_id,
            )
        return {"created": created, "total_created": len(created)}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
