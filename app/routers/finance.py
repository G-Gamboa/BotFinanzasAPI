from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_db
from app.schemas.finance import (
    SaldoItem,
    NetworthResponse,
    NetoResponse,
    DebtsResponse,
)
from app.services.finance_db_service import (
    build_saldos_map,
    build_networth,
    build_neto,
    build_debts,
)

router = APIRouter(tags=["finance"])


@router.get("/saldos/{telegram_user_id}", response_model=list[SaldoItem])
def saldos(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        saldos_map = build_saldos_map(db, telegram_user_id)
        return [{"cuenta": k, "saldo": round(v, 2)} for k, v in saldos_map.items()]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/networth/{telegram_user_id}", response_model=NetworthResponse)
def networth(telegram_user_id: int, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        return build_networth(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/neto/{telegram_user_id}", response_model=NetoResponse)
def neto(telegram_user_id: int, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        return build_neto(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/deudas/{telegram_user_id}", response_model=DebtsResponse)
def deudas(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return build_debts(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))