import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.dependencies import ensure_payload_user, ensure_same_user, get_current_app_user
from app.limiter import limiter
from app.services import shared_goal_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["shared-goals"])


class SharedGoalCreate(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    target_date: str | None = Field(default=None, max_length=10)
    partner_ids: list[int] = Field(min_length=1, max_length=10)


class SharedGoalUpdate(BaseModel):
    telegram_user_id: int
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    target_date: str | None = Field(default=None, max_length=10)


class SharedGoalMove(BaseModel):
    telegram_user_id: int
    amount: float = Field(gt=0)
    account_name: str = Field(min_length=1, max_length=100)
    movement_date: str = Field(max_length=10)


@router.get("/metas-conjuntas/{telegram_user_id}")
def listar(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    return svc.list_shared_goals(db, telegram_user_id)


@router.post("/metas-conjuntas")
@limiter.limit("20/minute")
def crear(
    request: Request,
    payload: SharedGoalCreate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        goal = svc.create_shared_goal(
            db, payload.telegram_user_id, payload.name, payload.target_amount,
            payload.target_date, payload.partner_ids,
        )
        logger.info("Meta conjunta creada: id=%s usuario=%s", goal.id, current_user.telegram_user_id)
        return {"id": int(goal.id), "ok": True, "message": "Meta conjunta creada."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/metas-conjuntas/{goal_id}")
def editar(
    goal_id: int,
    payload: SharedGoalUpdate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        svc.update_shared_goal(
            db, payload.telegram_user_id, goal_id, payload.name, payload.target_amount, payload.target_date,
        )
        return {"id": goal_id, "ok": True, "message": "Meta conjunta actualizada."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/metas-conjuntas/{goal_id}")
def cerrar(
    goal_id: int,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        svc.close_shared_goal(db, telegram_user_id, goal_id)
        return {"id": goal_id, "ok": True, "message": "Meta conjunta cerrada."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/metas-conjuntas/{goal_id}/aportar")
@limiter.limit("30/minute")
def aportar(
    request: Request,
    goal_id: int,
    payload: SharedGoalMove,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        goal = svc.contribute(
            db, payload.telegram_user_id, goal_id, payload.amount, payload.account_name, payload.movement_date,
        )
        return {"ok": True, "message": "Aporte registrado.", "goal": goal}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/metas-conjuntas/{goal_id}/retirar")
@limiter.limit("30/minute")
def retirar(
    request: Request,
    goal_id: int,
    payload: SharedGoalMove,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        goal = svc.withdraw(
            db, payload.telegram_user_id, goal_id, payload.amount, payload.account_name, payload.movement_date,
        )
        return {"ok": True, "message": "Retiro registrado.", "goal": goal}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
