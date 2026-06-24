import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user
from app.limiter import limiter
from app.schemas.configuration import (
    LoanPersonListResponse,
    LoanPersonCreateRequest,
    LoanPersonUpdateRequest,
    LoanPersonActionResponse,
)
from app.services.configuration_service import (
    list_loan_people,
    create_loan_person,
    update_loan_person,
    set_loan_person_active,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["loan_people"])


@router.get("/loan-people/{telegram_user_id}", response_model=LoanPersonListResponse)
def loan_people(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return list_loan_people(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/loan-people", response_model=LoanPersonActionResponse)
@limiter.limit("20/minute")
def crear_loan_person(
    request: Request,
    payload: LoanPersonCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        person = create_loan_person(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
        )
        return {"id": int(person.id), "ok": True, "message": "Persona creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/loan-people/{loan_person_id}", response_model=LoanPersonActionResponse)
def editar_loan_person(
    loan_person_id: int,
    payload: LoanPersonUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)
    try:
        person = update_loan_person(
            db=db,
            loan_person_id=loan_person_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
        )
        return {"id": int(person.id), "ok": True, "message": "Persona actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/loan-people/{loan_person_id}/activar", response_model=LoanPersonActionResponse)
def activar_loan_person(
    loan_person_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        person = set_loan_person_active(db, loan_person_id, current_user.telegram_user_id, True)
        return {"id": int(person.id), "ok": True, "message": "Persona activada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/loan-people/{loan_person_id}/desactivar", response_model=LoanPersonActionResponse)
def desactivar_loan_person(
    loan_person_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        person = set_loan_person_active(db, loan_person_id, current_user.telegram_user_id, False)
        return {"id": int(person.id), "ok": True, "message": "Persona desactivada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
