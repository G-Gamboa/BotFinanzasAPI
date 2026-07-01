import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.budget import (
    BudgetCreateRequest,
    BudgetUpdateRequest,
    BudgetListResponse,
    BudgetActionResponse,
)
from app.services.budget_service import (
    list_budgets,
    create_budget,
    update_budget,
    delete_budget,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["budget"])


@router.get("/presupuesto/{telegram_user_id}", response_model=BudgetListResponse)
def get_presupuesto(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        items = list_budgets(db, telegram_user_id)
        return {"items": items}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/presupuesto", response_model=BudgetActionResponse)
@limiter.limit("30/minute")
def crear_presupuesto(
    request: Request,
    payload: BudgetCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        budget = create_budget(db, payload.telegram_user_id, payload.category_id, payload.monthly_amount)
        logger.info("Presupuesto creado: id=%s usuario=%s", budget.id, current_user.telegram_user_id)
        return {"id": int(budget.id), "ok": True, "message": "Presupuesto creado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/presupuesto/{budget_id}", response_model=BudgetActionResponse)
def editar_presupuesto(
    budget_id: int,
    payload: BudgetUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        budget = update_budget(db, budget_id, payload.telegram_user_id, payload.monthly_amount)
        logger.info("Presupuesto editado: id=%s usuario=%s", budget.id, current_user.telegram_user_id)
        return {"id": int(budget.id), "ok": True, "message": "Presupuesto actualizado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/presupuesto/{budget_id}", response_model=BudgetActionResponse)
def eliminar_presupuesto(
    budget_id: int,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        delete_budget(db, budget_id, telegram_user_id)
        logger.info("Presupuesto eliminado: id=%s usuario=%s", budget_id, current_user.telegram_user_id)
        return {"id": budget_id, "ok": True, "message": "Presupuesto eliminado correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
