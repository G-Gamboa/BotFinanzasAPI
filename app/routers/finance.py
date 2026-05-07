import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.db.models import User
from app.limiter import limiter
from app.security.telegram_auth import get_current_telegram_auth

logger = logging.getLogger(__name__)
from app.schemas.loans_view import LoansViewResponse
from app.services.loans_view_service import build_loans_view
from app.schemas.movements_void import MovementVoidRequest, MovementUpdateRequest
from app.services.transaction_service import void_movement, update_movement

# =========================
# Schemas - Finanzas
# =========================
from app.schemas.finance import (
    SaldoItem,
    NetworthResponse,
    NetoResponse,
    DebtsResponse,
    DashboardResponse,
)

# =========================
# Services - Finanzas
# =========================
from app.services.finance_db_service import (
    build_saldos_map,
    build_networth,
    build_neto,
    build_debts,
    build_dashboard,
    build_period_summary,
)

# =========================
# Schemas - Movimientos
# =========================
from app.schemas.transactions import (
    MovementCreateRequest,
    MovementCreateResponse,
)

# =========================
# Services - Movimientos
# =========================
from app.services.transaction_service import create_movement

# =========================
# Schemas - Catálogos / Disponibles
# =========================
from app.schemas.catalogs import CatalogsResponse
from app.schemas.availability import DisponiblesResponse

# =========================
# Services - Catálogos / Disponibles
# =========================
from app.services.catalog_service import build_catalogs
from app.services.availability_service import build_disponibles

# =========================
# Schemas - Deudas
# =========================
from app.schemas.debts import (
    DebtCreateRequest,
    DebtCreateResponse,
    DebtPayRequest,
    DebtPayResponse,
)

# =========================
# Services - Deudas
# =========================
from app.services.debt_service import create_debt, pay_debt

# =========================
# Schemas - Configuración
# =========================
from app.schemas.configuration import (
    AccountListResponse,
    AccountCreateRequest,
    AccountUpdateRequest,
    AccountActionResponse,
    CategoryListResponse,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CategoryActionResponse,
    LoanPersonListResponse,
    LoanPersonCreateRequest,
    LoanPersonUpdateRequest,
    LoanPersonActionResponse,
)

# =========================
# Services - Configuración
# =========================
from app.services.configuration_service import (
    list_accounts,
    create_account,
    update_account,
    set_account_active,
    list_categories,
    create_category,
    update_category,
    set_category_active,
    list_loan_people,
    create_loan_person,
    update_loan_person,
    set_loan_person_active,
)

# =========================
# Schemas - Preferencias
# =========================
from app.schemas.preferences import (
    PreferencesResponse,
    PreferencesUpdateRequest,
    PreferencesUpdateResponse,
)

# =========================
# Services - Preferencias
# =========================
from app.services.preferences_service import (
    get_preferences,
    update_preferences,
)

# =========================
# Schemas - Historial
# =========================
from app.schemas.history import HistoryResponse

# =========================
# Services - Historial
# =========================
from app.services.history_service import build_history, void_loan_payment, void_debt_payment


router = APIRouter(tags=["finance"])


# =========================================================
# AUTH HELPERS
# =========================================================
def get_current_app_user(
    auth=Depends(get_current_telegram_auth),
    db: Session = Depends(get_db),
) -> User:
    telegram_user_id = auth["user"]["id"]

    user = db.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    if not user:
        logger.warning("Acceso denegado: telegram_user_id=%s no registrado.", telegram_user_id)
        raise HTTPException(status_code=403, detail="Usuario no registrado.")

    return user


def ensure_same_user(route_telegram_user_id: int, current_user: User):
    if route_telegram_user_id != current_user.telegram_user_id:
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")


def ensure_payload_user(payload_telegram_user_id: int, current_user: User):
    if payload_telegram_user_id != current_user.telegram_user_id:
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")


# =========================================================
# GET - FINANZAS
# =========================================================
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
    from datetime import datetime
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


@router.get("/catalogos/{telegram_user_id}", response_model=CatalogsResponse)
def catalogos(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    settings = get_settings()
    try:
        return build_catalogs(db, telegram_user_id, settings)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/disponibles/{telegram_user_id}", response_model=DisponiblesResponse)
def disponibles(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return build_disponibles(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cuentas/{telegram_user_id}", response_model=AccountListResponse)
def cuentas(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return list_accounts(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/categorias/{telegram_user_id}", response_model=CategoryListResponse)
def categorias(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return list_categories(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


# =========================================================
# GET - PREFERENCIAS
# =========================================================
@router.get("/preferencias/{telegram_user_id}", response_model=PreferencesResponse)
def preferencias(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return get_preferences(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =========================================================
# GET - HISTORIAL
# =========================================================
@router.get("/historial/{telegram_user_id}", response_model=HistoryResponse)
def historial(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    note: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(0, offset)
        return build_history(
            db,
            telegram_user_id,
            date_from=date_from,
            date_to=date_to,
            movement_type=movement_type,
            note=note,
            limit=safe_limit,
            offset=safe_offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# =========================================================
# GET - PRESTAMOS VISTA
# =========================================================
@router.get("/prestamos/{telegram_user_id}", response_model=LoansViewResponse)
def prestamos_view(
    telegram_user_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_same_user(telegram_user_id, current_user)
    try:
        return build_loans_view(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# =========================================================
# POST - LOAN PEOPLE
# =========================================================
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
        return {
            "id": int(person.id),
            "ok": True,
            "message": "Persona creada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# POST - MOVIMIENTOS
# =========================================================
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
        return {
            "id": int(movement.id),
            "ok": True,
            "message": "Movimiento creado correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        db.rollback()
        raise


# =========================================================
# POST - DEUDAS
# =========================================================
@router.post("/deudas", response_model=DebtCreateResponse)
@limiter.limit("20/minute")
def crear_deuda(
    request: Request,
    payload: DebtCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        debt = create_debt(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            creditor=payload.creditor,
            due_date=payload.due_date,
            installment_amount=payload.installment_amount,
            total_installments=payload.total_installments,
            paid_installments=payload.paid_installments,
        )
        logger.info("Deuda creada: id=%s usuario=%s", debt.id, current_user.telegram_user_id)
        return {
            "id": int(debt.id),
            "ok": True,
            "message": "Deuda creada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deudas/pagar", response_model=DebtPayResponse)
@limiter.limit("20/minute")
def pagar_deuda(
    request: Request,
    payload: DebtPayRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        debt = pay_debt(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            debt_id=payload.debt_id,
            payment_date=payload.payment_date,
            payment_method=payload.payment_method,
            account_name=payload.account_name,
            note=payload.note,
        )
        pending = max(debt.total_installments - debt.paid_installments, 0)
        logger.info("Deuda pagada: id=%s cuotas_pagadas=%s usuario=%s", debt.id, debt.paid_installments, current_user.telegram_user_id)
        return {
            "debt_id": int(debt.id),
            "ok": True,
            "message": "Pago registrado correctamente.",
            "paid_installments": int(debt.paid_installments),
            "pending_installments": int(pending),
            "status": debt.status,
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# POST - CUENTAS
# =========================================================
@router.post("/cuentas", response_model=AccountActionResponse)
@limiter.limit("20/minute")
def crear_cuenta(
    request: Request,
    payload: AccountCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        account = create_account(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            account_type=payload.account_type,
            currency=payload.currency,
            sort_order=payload.sort_order,
        )
        return {
            "id": int(account.id),
            "ok": True,
            "message": "Cuenta creada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# POST - CATEGORÍAS
# =========================================================
@router.post("/categorias", response_model=CategoryActionResponse)
@limiter.limit("20/minute")
def crear_categoria(
    request: Request,
    payload: CategoryCreateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        category = create_category(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {
            "id": int(category.id),
            "ok": True,
            "message": "Categoría creada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - EDITAR MOVIMIENTO
# =========================================================
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
        )
        logger.info("Movimiento editado: id=%s usuario=%s", movement.id, current_user.telegram_user_id)
        return {
            "message": "Movimiento actualizado correctamente.",
            "movement_id": movement.id,
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - ANULAR MOVIMIENTO
# =========================================================
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
        return {
            "message": "Movimiento anulado correctamente.",
            "movement_id": movement.id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# =========================================================
# PATCH - ANULAR COBRO (loan_payment)
# =========================================================
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
        return {"message": "Cobro anulado correctamente.", "id": lp.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - ANULAR PAGO DE DEUDA (debt_payment)
# =========================================================
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
        return {"message": "Pago de deuda anulado correctamente.", "id": dp.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - CUENTAS
# =========================================================
@router.patch("/cuentas/{account_id}", response_model=AccountActionResponse)
def editar_cuenta(
    account_id: int,
    payload: AccountUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        account = update_account(
            db=db,
            account_id=account_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            account_type=payload.account_type,
            currency=payload.currency,
            sort_order=payload.sort_order,
        )
        return {
            "id": int(account.id),
            "ok": True,
            "message": "Cuenta actualizada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/activar", response_model=AccountActionResponse)
def activar_cuenta(
    account_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        account = set_account_active(db, account_id, current_user.telegram_user_id, True)
        return {
            "id": int(account.id),
            "ok": True,
            "message": "Cuenta activada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/desactivar", response_model=AccountActionResponse)
def desactivar_cuenta(
    account_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        account = set_account_active(db, account_id, current_user.telegram_user_id, False)
        return {
            "id": int(account.id),
            "ok": True,
            "message": "Cuenta desactivada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - CATEGORÍAS
# =========================================================
@router.patch("/categorias/{category_id}", response_model=CategoryActionResponse)
def editar_categoria(
    category_id: int,
    payload: CategoryUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        category = update_category(
            db=db,
            category_id=category_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {
            "id": int(category.id),
            "ok": True,
            "message": "Categoría actualizada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/activar", response_model=CategoryActionResponse)
def activar_categoria(
    category_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        category = set_category_active(db, category_id, current_user.telegram_user_id, True)
        return {
            "id": int(category.id),
            "ok": True,
            "message": "Categoría activada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/desactivar", response_model=CategoryActionResponse)
def desactivar_categoria(
    category_id: int,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        category = set_category_active(db, category_id, current_user.telegram_user_id, False)
        return {
            "id": int(category.id),
            "ok": True,
            "message": "Categoría desactivada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - LOAN PEOPLE
# =========================================================
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
        return {
            "id": int(person.id),
            "ok": True,
            "message": "Persona actualizada correctamente.",
        }
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
        return {
            "id": int(person.id),
            "ok": True,
            "message": "Persona activada correctamente.",
        }
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
        return {
            "id": int(person.id),
            "ok": True,
            "message": "Persona desactivada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
# PATCH - PREFERENCIAS
# =========================================================
@router.patch("/preferencias", response_model=PreferencesUpdateResponse)
def actualizar_preferencias(
    payload: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    ensure_payload_user(payload.telegram_user_id, current_user)

    try:
        update_preferences(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            show_amounts_default=payload.show_amounts_default,
            default_tab=payload.default_tab,
            usd_to_gtq=payload.usd_to_gtq,
            theme_key=payload.theme_key,
        )
        return {
            "ok": True,
            "message": "Preferencias actualizadas correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))