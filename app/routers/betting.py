"""
Betting Tracker — acceso exclusivo para admin.
No interfiere con saldos ni movimientos financieros.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import BettingBet, BettingConfig, User
from app.routers.admin import require_admin
from app.schemas.betting import (
    BetItem,
    BettingConfigSchema,
    BettingResponse,
    CreateBetRequest,
    UpdateBetRequest,
    UpdateConfigRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/betting", tags=["betting"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_create_config(db: Session) -> BettingConfig:
    cfg = db.scalar(select(BettingConfig).where(BettingConfig.id == 1))
    if not cfg:
        cfg = BettingConfig(id=1, bank_inicial=Decimal("750"), meta=Decimal("20000"))
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _calc_ganancia(estado: str, stake: Decimal, cuota: Decimal) -> Decimal | None:
    if estado == "ganada":
        return (stake * (cuota - Decimal("1"))).quantize(Decimal("0.01"))
    if estado == "perdida":
        return -stake
    if estado == "void":
        return Decimal("0")
    return None  # pendiente


def _bet_to_dict(b: BettingBet) -> dict:
    return {
        "id":       b.id,
        "fecha":    b.fecha,
        "deporte":  b.deporte,
        "partido":  b.partido,
        "pick":     b.pick,
        "cuota":    float(b.cuota),
        "stake":    float(b.stake),
        "estado":   b.estado,
        "ganancia": float(b.ganancia) if b.ganancia is not None else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=BettingResponse)
def get_bets(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    bets = db.scalars(select(BettingBet).order_by(BettingBet.created_at, BettingBet.id)).all()
    cfg  = _get_or_create_config(db)
    return {
        "items":  [_bet_to_dict(b) for b in bets],
        "config": {"bank_inicial": float(cfg.bank_inicial), "meta": float(cfg.meta)},
    }


@router.post("", response_model=BetItem)
def create_bet(
    payload: CreateBetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    cuota = Decimal(str(payload.cuota))
    stake = Decimal(str(payload.stake))
    gan   = _calc_ganancia(payload.estado, stake, cuota)

    bet = BettingBet(
        fecha=payload.fecha,
        deporte=payload.deporte,
        partido=payload.partido,
        pick=payload.pick,
        cuota=cuota,
        stake=stake,
        estado=payload.estado,
        ganancia=gan,
        created_at=datetime.now(timezone.utc),
    )
    db.add(bet)
    db.commit()
    db.refresh(bet)
    logger.info("Bet created id=%s pick=%s", bet.id, bet.pick)
    return _bet_to_dict(bet)


@router.patch("/{bet_id}", response_model=BetItem)
def update_bet(
    bet_id: int,
    payload: UpdateBetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    bet = db.scalar(select(BettingBet).where(BettingBet.id == bet_id))
    if not bet:
        raise HTTPException(status_code=404, detail="Apuesta no encontrada.")

    if payload.fecha   is not None: bet.fecha   = payload.fecha
    if payload.deporte is not None: bet.deporte = payload.deporte
    if payload.partido is not None: bet.partido = payload.partido
    if payload.pick    is not None: bet.pick    = payload.pick
    if payload.cuota   is not None: bet.cuota   = Decimal(str(payload.cuota))
    if payload.stake   is not None: bet.stake   = Decimal(str(payload.stake))

    if payload.estado is not None:
        bet.estado = payload.estado

    # Recalcular ganancia siempre que cambie estado o stake/cuota
    if any(v is not None for v in [payload.estado, payload.stake, payload.cuota]):
        bet.ganancia = _calc_ganancia(bet.estado, bet.stake, bet.cuota)

    db.commit()
    db.refresh(bet)
    return _bet_to_dict(bet)


@router.delete("/{bet_id}")
def delete_bet(
    bet_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    bet = db.scalar(select(BettingBet).where(BettingBet.id == bet_id))
    if not bet:
        raise HTTPException(status_code=404, detail="Apuesta no encontrada.")
    db.delete(bet)
    db.commit()
    return {"ok": True}


@router.patch("/config/update", response_model=BettingConfigSchema)
def update_config(
    payload: UpdateConfigRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    cfg = _get_or_create_config(db)
    if payload.bank_inicial is not None:
        cfg.bank_inicial = Decimal(str(payload.bank_inicial))
    if payload.meta is not None:
        cfg.meta = Decimal(str(payload.meta))
    db.commit()
    db.refresh(cfg)
    return {"bank_inicial": float(cfg.bank_inicial), "meta": float(cfg.meta)}
