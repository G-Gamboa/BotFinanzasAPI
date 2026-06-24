import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.transactions import MovementCreateRequest, MovementCreateResponse
from app.schemas.movements_void import MovementVoidRequest, MovementUpdateRequest
from app.services.transaction_service import create_movement, void_movement, update_movement
from app.services.history_service import void_loan_payment, void_debt_payment
from app.ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["movements"])


@router.post("/movimientos", response_model=MovementCreateResponse)
@limiter.limit("30/minute")
def crear_movimiento(
    request: Request,
    payload: MovementCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        movement = create_movement(db, payload)
        logger.info("Movimiento creado: id=%s tipo=%s usuario=%s", movement.id, payload.movement_type, current_user.telegram_user_id)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"id": int(movement.id), "ok": True, "message": "Movimiento creado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        db.rollback()
        raise


@router.patch("/movimientos/{movement_id}")
def editar_movimiento(
    movement_id: int,
    payload: MovementUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        movement = update_movement(
            db=db,
            telegram_user_id=current_user.telegram_user_id,
            movement_id=movement_id,
            movement_date=payload.movement_date,
            amount=payload.amount,
            note=payload.note,
            category_name=payload.category_name,
            payment_method=payload.payment_method,
            credit_card_account_id=payload.credit_card_account_id,
        )
        logger.info("Movimiento editado: id=%s usuario=%s", movement.id, current_user.telegram_user_id)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"message": "Movimiento actualizado correctamente.", "movement_id": movement.id}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/movimientos/{movement_id}/anular")
def anular_movimiento(
    movement_id: int,
    payload: MovementVoidRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        movement = void_movement(
            db=db,
            telegram_user_id=current_user.telegram_user_id,
            movement_id=movement_id,
            reason=payload.reason,
        )
        logger.info("Movimiento anulado: id=%s usuario=%s motivo=%s", movement.id, current_user.telegram_user_id, payload.reason)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"message": "Movimiento anulado correctamente.", "movement_id": movement.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/loan-payments/{loan_payment_id}/anular")
def anular_loan_payment(
    loan_payment_id: int,
    payload: MovementVoidRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        lp = void_loan_payment(
            db=db,
            telegram_user_id=current_user.telegram_user_id,
            loan_payment_id=loan_payment_id,
            reason=payload.reason,
        )
        logger.info("LoanPayment anulado: id=%s usuario=%s", lp.id, current_user.telegram_user_id)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"message": "Cobro anulado correctamente.", "id": lp.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/debt-payments/{debt_payment_id}/anular")
def anular_debt_payment(
    debt_payment_id: int,
    payload: MovementVoidRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        dp = void_debt_payment(
            db=db,
            telegram_user_id=current_user.telegram_user_id,
            debt_payment_id=debt_payment_id,
            reason=payload.reason,
        )
        logger.info("DebtPayment anulado: id=%s usuario=%s", dp.id, current_user.telegram_user_id)
        manager.broadcast_from_sync(current_user.telegram_user_id, {"event": "invalidate", "scope": "financial"})
        return {"message": "Pago de deuda anulado correctamente.", "id": dp.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
