import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.security.telegram_auth import get_current_telegram_auth
from app.services.availability_service import build_disponibles
from app.services.budget_service import list_budgets
from app.services.calendar_service import build_calendar
from app.services.catalog_service import build_catalogs
from app.services.configuration_service import list_accounts, list_categories, list_loan_people
from app.services.finance_context import FinanceContext
from app.services.finance_db_service import build_cc_balances, build_dashboard, build_debts, today_gt
from app.services.installment_service import list_installment_plans, process_pending_charges
from app.services.preferences_service import get_preferences
from app.services.subscription_service import days_remaining, subscription_active

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bootstrap"])


@router.get("/bootstrap/{telegram_user_id}")
def bootstrap(
    telegram_user_id: int,
    auth=Depends(get_current_telegram_auth),
    db: Session = Depends(get_db),
):
    """Todo lo que la app necesita al abrir, en una sola respuesta."""
    if auth["user"]["id"] != telegram_user_id:
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")

    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None or not subscription_active(user):
        return {"registered": False, "days_remaining": days_remaining(user) if user else None}
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuario inactivo.")

    remaining = days_remaining(user)

    # Las escrituras van antes de cargar el contexto: un commit invalida lo cargado.
    auto_charges = 0
    try:
        auto_charges = len(process_pending_charges(db, telegram_user_id))
    except Exception:
        db.rollback()
        logger.exception("No se pudieron generar los cargos de visacuotas de usuario=%s", telegram_user_id)
    preferencias = get_preferences(db, telegram_user_id)

    settings = get_settings()
    today = today_gt()
    ctx = FinanceContext(db, telegram_user_id)

    return {
        "registered": True,
        "days_remaining": remaining,
        "auto_charges": auto_charges,
        "catalogos": build_catalogs(db, telegram_user_id, settings, ctx),
        "dashboard": build_dashboard(db, telegram_user_id, settings.usd_to_gtq, ctx),
        "disponibles": build_disponibles(db, telegram_user_id, ctx),
        "deudas": build_debts(db, telegram_user_id, ctx),
        "cuentas": list_accounts(db, telegram_user_id),
        "categorias": list_categories(db, telegram_user_id),
        "loanPeople": list_loan_people(db, telegram_user_id),
        "preferencias": preferencias,
        "tcBalances": {"items": build_cc_balances(db, telegram_user_id, ctx)},
        "installmentPlans": {"items": list_installment_plans(db, telegram_user_id, ctx)},
        "presupuesto": {"items": list_budgets(db, telegram_user_id)},
        "calendario": build_calendar(db, telegram_user_id, today.year, today.month, ctx),
    }
