import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User, SavingsGoal
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.savings import (
    SavingsGoalsResponse,
    SavingsGoalCreateRequest,
    SavingsGoalUpdateRequest,
    SavingsGoalActionResponse,
)
from app.services.finance_db_service import build_savings_goals as _build_savings_goals

logger = logging.getLogger(__name__)
router = APIRouter(tags=["savings"])


@router.get("/savings-goals/{telegram_user_id}", response_model=SavingsGoalsResponse)
def get_savings_goals(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    goals = _build_savings_goals(db, telegram_user_id)
    return {"items": goals}


@router.post("/savings-goals", response_model=SavingsGoalActionResponse)
@limiter.limit("30/minute")
def crear_savings_goal(
    request: Request,
    payload: SavingsGoalCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    goal = SavingsGoal(
        user_id=current_user.id,
        name=payload.name.strip(),
        target_amount=payload.target_amount,
        account_name=payload.account_name.strip() if payload.account_name else None,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {"id": int(goal.id), "ok": True, "message": "Meta creada correctamente."}


@router.patch("/savings-goals/{goal_id}", response_model=SavingsGoalActionResponse)
def editar_savings_goal(
    goal_id: int,
    payload: SavingsGoalUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    goal = db.scalar(select(SavingsGoal).where(SavingsGoal.id == goal_id, SavingsGoal.user_id == current_user.id))
    if not goal:
        raise HTTPException(status_code=404, detail="Meta no encontrada.")
    goal.name = payload.name.strip()
    goal.target_amount = payload.target_amount
    goal.account_name = payload.account_name.strip() if payload.account_name else None
    db.commit()
    return {"id": int(goal.id), "ok": True, "message": "Meta actualizada correctamente."}


@router.delete("/savings-goals/{goal_id}", response_model=SavingsGoalActionResponse)
def eliminar_savings_goal(
    goal_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    goal = db.scalar(select(SavingsGoal).where(SavingsGoal.id == goal_id, SavingsGoal.user_id == current_user.id))
    if not goal:
        raise HTTPException(status_code=404, detail="Meta no encontrada.")
    goal.is_active = False
    db.commit()
    return {"id": int(goal.id), "ok": True, "message": "Meta eliminada correctamente."}
