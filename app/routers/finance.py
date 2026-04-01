from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas.finance import DashboardResponse
from app.services.finance_db_service import build_dashboard

from app.schemas.transactions import MovementCreateRequest, MovementCreateResponse
from app.services.transaction_service import create_movement

from app.schemas.catalogs import CatalogsResponse
from app.services.catalog_service import build_catalogs

from app.schemas.availability import DisponiblesResponse
from app.services.availability_service import build_disponibles

from app.schemas.preferences import (
    PreferencesResponse,
    PreferencesUpdateRequest,
    PreferencesUpdateResponse,
)
from app.services.preferences_service import (
    get_preferences,
    update_preferences,
)

from app.schemas.debts import (
    DebtCreateRequest,
    DebtCreateResponse,
    DebtPayRequest,
    DebtPayResponse,
)
from app.services.debt_service import create_debt, pay_debt

from app.schemas.configuration import (
    AccountListResponse,
    AccountCreateRequest,
    AccountUpdateRequest,
    AccountActionResponse,
    CategoryListResponse,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CategoryActionResponse,
)
from app.services.configuration_service import (
    list_accounts,
    create_account,
    update_account,
    set_account_active,
    list_categories,
    create_category,
    update_category,
    set_category_active,
)

from app.schemas.history import HistoryResponse
from app.services.history_service import build_history


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
    

@router.get("/dashboard/{telegram_user_id}", response_model=DashboardResponse)
def dashboard(telegram_user_id: int, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        return build_dashboard(db, telegram_user_id, settings.usd_to_gtq)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    

@router.post("/movimientos", response_model=MovementCreateResponse)
def crear_movimiento(payload: MovementCreateRequest, db: Session = Depends(get_db)):
    try:
        movement = create_movement(db, payload)
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


@router.get("/catalogos/{telegram_user_id}", response_model=CatalogsResponse)
def catalogos(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return build_catalogs(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    

@router.get("/disponibles/{telegram_user_id}", response_model=DisponiblesResponse)
def disponibles(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return build_disponibles(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    

@router.post("/deudas", response_model=DebtCreateResponse)
def crear_deuda(payload: DebtCreateRequest, db: Session = Depends(get_db)):
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
        return {
            "id": int(debt.id),
            "ok": True,
            "message": "Deuda creada correctamente.",
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deudas/pagar", response_model=DebtPayResponse)
def pagar_deuda(payload: DebtPayRequest, db: Session = Depends(get_db)):
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
    

@router.get("/cuentas/{telegram_user_id}", response_model=AccountListResponse)
def cuentas(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return list_accounts(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/cuentas", response_model=AccountActionResponse)
def crear_cuenta(payload: AccountCreateRequest, db: Session = Depends(get_db)):
    try:
        account = create_account(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            account_type=payload.account_type,
            currency=payload.currency,
            sort_order=payload.sort_order,
        )
        return {"id": int(account.id), "ok": True, "message": "Cuenta creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}", response_model=AccountActionResponse)
def editar_cuenta(account_id: int, payload: AccountUpdateRequest, db: Session = Depends(get_db)):
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
        return {"id": int(account.id), "ok": True, "message": "Cuenta actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/activar", response_model=AccountActionResponse)
def activar_cuenta(account_id: int, telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        account = set_account_active(db, account_id, telegram_user_id, True)
        return {"id": int(account.id), "ok": True, "message": "Cuenta activada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/cuentas/{account_id}/desactivar", response_model=AccountActionResponse)
def desactivar_cuenta(account_id: int, telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        account = set_account_active(db, account_id, telegram_user_id, False)
        return {"id": int(account.id), "ok": True, "message": "Cuenta desactivada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/categorias/{telegram_user_id}", response_model=CategoryListResponse)
def categorias(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return list_categories(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/categorias", response_model=CategoryActionResponse)
def crear_categoria(payload: CategoryCreateRequest, db: Session = Depends(get_db)):
    try:
        category = create_category(
            db=db,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {"id": int(category.id), "ok": True, "message": "Categoría creada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}", response_model=CategoryActionResponse)
def editar_categoria(category_id: int, payload: CategoryUpdateRequest, db: Session = Depends(get_db)):
    try:
        category = update_category(
            db=db,
            category_id=category_id,
            telegram_user_id=payload.telegram_user_id,
            name=payload.name,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {"id": int(category.id), "ok": True, "message": "Categoría actualizada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/activar", response_model=CategoryActionResponse)
def activar_categoria(category_id: int, telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        category = set_category_active(db, category_id, telegram_user_id, True)
        return {"id": int(category.id), "ok": True, "message": "Categoría activada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/categorias/{category_id}/desactivar", response_model=CategoryActionResponse)
def desactivar_categoria(category_id: int, telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        category = set_category_active(db, category_id, telegram_user_id, False)
        return {"id": int(category.id), "ok": True, "message": "Categoría desactivada correctamente."}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    

@router.get("/preferencias/{telegram_user_id}", response_model=PreferencesResponse)
def preferencias(telegram_user_id: int, db: Session = Depends(get_db)):
    try:
        return get_preferences(db, telegram_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/preferencias", response_model=PreferencesUpdateResponse)
def actualizar_preferencias(payload: PreferencesUpdateRequest, db: Session = Depends(get_db)):
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
    



@router.get("/historial/{telegram_user_id}", response_model=HistoryResponse)
def historial(
    telegram_user_id: int,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    limit: int = 50,
):
    try:
        safe_limit = max(1, min(limit, 200))
        return build_history(
            db,
            telegram_user_id,
            date_from=date_from,
            date_to=date_to,
            movement_type=movement_type,
            limit=safe_limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))