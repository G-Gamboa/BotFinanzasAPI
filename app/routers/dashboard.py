import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user
from app.schemas.finance import SaldoItem, NetworthResponse, NetoResponse, DebtsResponse, DashboardResponse
from app.services.finance_db_service import (
    build_saldos_map,
    build_networth,
    build_neto,
    build_debts,
    build_dashboard,
    build_period_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


@router.get("/saldos/{telegram_user_id}", response_model=list[SaldoItem])
def saldos(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        saldos_map = build_saldos_map(db, telegram_user_id)
        return [{"cuenta": k, "saldo": round(v, 2)} for k, v in saldos_map.items()]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/networth/{telegram_user_id}", response_model=NetworthResponse)
def networth(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    settings = get_settings()
    try:
        return build_networth(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/neto/{telegram_user_id}", response_model=NetoResponse)
def neto(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    settings = get_settings()
    try:
        return build_neto(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/deudas/{telegram_user_id}", response_model=DebtsResponse)
def deudas(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return build_debts(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/dashboard/{telegram_user_id}", response_model=DashboardResponse)
def dashboard(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    settings = get_settings()
    try:
        return build_dashboard(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/dashboard/{telegram_user_id}/periodo")
def dashboard_periodo(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        if not date_from or not date_to:
            raise ValueError("Se requieren date_from y date_to.")
        try:
            fecha_inicio = datetime.strptime(date_from, "%Y-%m-%d").date()
            fecha_fin = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Las fechas deben usar formato YYYY-MM-DD.")
        if fecha_inicio > fecha_fin:
            raise ValueError("date_from no puede ser mayor que date_to.")
        return build_period_summary(db, telegram_user_id, "custom", fecha_inicio, fecha_fin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
