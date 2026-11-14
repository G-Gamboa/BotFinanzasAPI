import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.dependencies import ensure_payload_user, ensure_same_user, get_current_app_user
from app.limiter import limiter
from app.schemas.calendar import (
    ConfirmDebt,
    ConfirmScheduled,
    NoteCreate,
    OccurrenceUpdate,
    ScheduledItemCreate,
    ScheduledItemUpdate,
)
from app.services import calendar_service as svc
from app.services.finance_db_service import today_gt
from app.ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["calendar"])


def _invalidate(user: User) -> None:
    manager.broadcast_from_sync(user.telegram_user_id, {"event": "invalidate", "scope": "financial"})


@router.get("/calendario/{telegram_user_id}")
def calendario(
    telegram_user_id: int,
    year: int | None = None,
    month: int | None = None,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    today = today_gt()
    year = year or today.year
    month = month or today.month
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        raise HTTPException(status_code=400, detail="Mes inválido.")
    try:
        return svc.build_calendar(db, telegram_user_id, year, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/calendario/items")
@limiter.limit("30/minute")
def crear_programado(
    request: Request,
    payload: ScheduledItemCreate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        item = svc.create_item(db, payload.telegram_user_id, payload)
        _invalidate(current_user)
        return {"id": int(item.id), "ok": True, "message": "Agregado al calendario."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/calendario/items/{item_id}")
def editar_programado(
    item_id: int,
    payload: ScheduledItemUpdate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        svc.update_item(db, payload.telegram_user_id, item_id, payload)
        _invalidate(current_user)
        return {"id": item_id, "ok": True, "message": "Programado actualizado."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/calendario/items/{item_id}")
def eliminar_programado(
    item_id: int,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        svc.delete_item(db, telegram_user_id, item_id)
        _invalidate(current_user)
        return {"id": item_id, "ok": True, "message": "Quitado del calendario."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/calendario/ocurrencia")
def editar_ocurrencia(
    payload: OccurrenceUpdate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        if payload.undo:
            svc.undo_reminder(db, payload.telegram_user_id, payload.item_id, payload.due_date)
        else:
            svc.set_occurrence(
                db, payload.telegram_user_id, payload.item_id, payload.due_date,
                amount=payload.amount, set_amount="amount" in payload.model_fields_set,
                skip=payload.skip,
            )
        _invalidate(current_user)
        return {"ok": True, "message": "Actualizado."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/calendario/confirmar")
@limiter.limit("30/minute")
def confirmar_programado(
    request: Request,
    payload: ConfirmScheduled,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        result = svc.confirm_scheduled(db, payload.telegram_user_id, payload)
        logger.info("Programado confirmado: item=%s usuario=%s", payload.item_id, current_user.telegram_user_id)
        _invalidate(current_user)
        return {"ok": True, "message": "Registrado correctamente.", **result}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/calendario/confirmar-deuda")
@limiter.limit("30/minute")
def confirmar_cuota_deuda(
    request: Request,
    payload: ConfirmDebt,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        result = svc.confirm_debt(db, payload.telegram_user_id, payload)
        _invalidate(current_user)
        return {"ok": True, "message": "Cuota registrada correctamente.", **result}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/calendario/notas")
def crear_nota(
    payload: NoteCreate,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    note = svc.add_note(db, payload.telegram_user_id, payload.text)
    return {"id": int(note.id), "ok": True}


@router.delete("/calendario/notas/{note_id}")
def eliminar_nota(
    note_id: int,
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        svc.delete_note(db, telegram_user_id, note_id)
        return {"id": note_id, "ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
