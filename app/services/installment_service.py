"""Servicio de planes de cuotas (Visacuotas) para tarjetas de crédito.

Responsabilidades:
- CRUD de CreditCardInstallmentPlan
- process_pending_charges: genera EGR automáticos para cuotas vencidas
- migrate_debt_to_tc: migra una deuda existente a TC (cargo normal o visacuotas)
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Category,
    CreditCardInstallmentPlan,
    Debt,
    Movement,
    User,
)
from app.schemas.installment_plans import (
    InstallmentPlanCreateRequest,
    MigrateDebtRequest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def _add_months(d: date, n: int) -> date:
    """Suma n meses a la fecha d, ajustando el día al último del mes si es necesario."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Fecha inválida: {value}. Use formato YYYY-MM-DD.")


def _count_paid(db: Session, plan_id: int) -> int:
    """Cuenta cuántos EGR movements activos están vinculados a este plan."""
    return db.scalar(
        select(func.count()).where(
            Movement.installment_plan_id == plan_id,
            Movement.is_void == False,
        )
    ) or 0


def _find_egr_category(db: Session, user_id: int) -> Category | None:
    """Busca la mejor categoría EGR para cargos automáticos de visacuotas."""
    preferred_names = ["visacuotas", "tarjeta de crédito", "tarjeta", "otros"]
    categories = db.scalars(
        select(Category).where(
            Category.user_id == user_id,
            Category.kind == "EGR",
            Category.is_active == True,
        )
    ).all()

    cat_by_name = {c.name.lower(): c for c in categories}
    for name in preferred_names:
        if name in cat_by_name:
            return cat_by_name[name]

    return categories[0] if categories else None


def _plan_to_dict(plan: CreditCardInstallmentPlan, paid: int, cc_name: str) -> dict:
    pending = max(plan.total_installments - paid, 0)
    remaining = round(pending * float(plan.monthly_amount), 2)

    if paid >= plan.total_installments:
        next_charge_date = None
        status = "completed"
    else:
        next_charge_date = _add_months(plan.first_charge_date, paid).isoformat()
        status = plan.status if plan.status != "completed" else "active"

    return {
        "id": int(plan.id),
        "credit_card_account_id": int(plan.credit_card_account_id),
        "credit_card_name": cc_name,
        "name": plan.name,
        "total_amount": float(plan.total_amount),
        "total_installments": plan.total_installments,
        "monthly_amount": float(plan.monthly_amount),
        "paid_installments": paid,
        "pending_installments": pending,
        "purchase_date": plan.purchase_date.isoformat(),
        "first_charge_date": plan.first_charge_date.isoformat(),
        "next_charge_date": next_charge_date,
        "remaining_amount": remaining,
        "status": status,
        "note": plan.note,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_installment_plans(db: Session, telegram_user_id: int) -> list[dict]:
    user = _get_user_or_raise(db, telegram_user_id)

    plans = db.scalars(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.is_active == True,
        ).order_by(CreditCardInstallmentPlan.first_charge_date, CreditCardInstallmentPlan.id)
    ).all()

    # Pre-load CC account names
    cc_ids = {p.credit_card_account_id for p in plans}
    cc_by_id: dict[int, str] = {}
    if cc_ids:
        accs = db.scalars(select(Account).where(Account.id.in_(cc_ids))).all()
        cc_by_id = {a.id: a.name for a in accs}

    result = []
    for plan in plans:
        paid = _count_paid(db, plan.id)
        cc_name = cc_by_id.get(plan.credit_card_account_id, "—")
        result.append(_plan_to_dict(plan, paid, cc_name))

    return result


def create_installment_plan(
    db: Session,
    req: InstallmentPlanCreateRequest,
) -> CreditCardInstallmentPlan:
    user = _get_user_or_raise(db, req.telegram_user_id)

    cc_account = db.scalar(
        select(Account).where(
            Account.id == req.credit_card_account_id,
            Account.user_id == user.id,
            Account.account_type == "credit_card",
            Account.is_active == True,
        )
    )
    if not cc_account:
        raise ValueError("Tarjeta de crédito no encontrada o inactiva.")

    purchase_date = _parse_date(req.purchase_date)
    first_charge_date = _parse_date(req.first_charge_date)

    if first_charge_date < purchase_date:
        raise ValueError("first_charge_date no puede ser anterior a purchase_date.")

    plan = CreditCardInstallmentPlan(
        user_id=user.id,
        credit_card_account_id=cc_account.id,
        name=req.name.strip(),
        total_amount=req.total_amount,
        total_installments=req.total_installments,
        monthly_amount=req.monthly_amount,
        purchase_date=purchase_date,
        first_charge_date=first_charge_date,
        status="active",
        note=(req.note or "").strip() or None,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_installment_plan(
    db: Session,
    plan_id: int,
    telegram_user_id: int,
    name: str,
    note: str | None,
) -> CreditCardInstallmentPlan:
    user = _get_user_or_raise(db, telegram_user_id)

    plan = db.scalar(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.id == plan_id,
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.is_active == True,
        )
    )
    if not plan:
        raise ValueError("Plan de cuotas no encontrado.")

    plan.name = name.strip()
    plan.note = (note or "").strip() or None
    db.commit()
    db.refresh(plan)
    return plan


def delete_installment_plan(
    db: Session,
    plan_id: int,
    telegram_user_id: int,
) -> CreditCardInstallmentPlan:
    user = _get_user_or_raise(db, telegram_user_id)

    plan = db.scalar(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.id == plan_id,
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.is_active == True,
        )
    )
    if not plan:
        raise ValueError("Plan de cuotas no encontrado.")

    plan.is_active = False
    plan.status = "cancelled"
    db.commit()
    db.refresh(plan)
    return plan


# ---------------------------------------------------------------------------
# Auto-generación de cargos pendientes
# ---------------------------------------------------------------------------

def process_pending_charges(db: Session, telegram_user_id: int) -> list[dict]:
    """Genera EGR movements para cuotas de Visacuotas que ya vencieron.

    Lógica:
    - Para cada plan activo, determina cuántas cuotas debieron haberse generado
      desde first_charge_date hasta hoy (inclusive).
    - Compara con las cuotas ya registradas (movements vinculados al plan).
    - Crea un EGR por cada cuota faltante.
    - Si paid == total_installments, marca el plan como 'completed'.
    """
    user = _get_user_or_raise(db, telegram_user_id)
    today = date.today()

    plans = db.scalars(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.is_active == True,
            CreditCardInstallmentPlan.status == "active",
        )
    ).all()

    if not plans:
        return []

    egr_category = _find_egr_category(db, user.id)

    created: list[dict] = []

    for plan in plans:
        paid = _count_paid(db, plan.id)

        # Determinar cuántas cuotas deben haberse cobrado hasta hoy
        due_count = 0
        for i in range(plan.total_installments):
            charge_date = _add_months(plan.first_charge_date, i)
            if charge_date <= today:
                due_count += 1
            else:
                break

        to_create = due_count - paid
        if to_create <= 0:
            continue

        cc_account = db.get(Account, plan.credit_card_account_id)
        if not cc_account:
            continue

        for i in range(to_create):
            charge_index = paid + i
            charge_date = _add_months(plan.first_charge_date, charge_index)

            movement = Movement(
                user_id=user.id,
                movement_type="EGR",
                movement_date=charge_date,
                amount=plan.monthly_amount,
                destination_amount=None,
                note=f"Visacuota: {plan.name}",
                source_account_id=None,
                target_account_id=None,
                category_id=egr_category.id if egr_category else None,
                payment_method="credit_card",
                transfer_account_id=None,
                loan_person_id=None,
                credit_card_account_id=cc_account.id,
                installment_plan_id=plan.id,
            )
            db.add(movement)
            db.flush()

            created.append({
                "plan_id": int(plan.id),
                "plan_name": plan.name,
                "amount": float(plan.monthly_amount),
                "charge_date": charge_date.isoformat(),
                "credit_card_name": cc_account.name,
            })

        # Actualizar estado del plan si ya se completó
        new_paid = paid + to_create
        if new_paid >= plan.total_installments:
            plan.status = "completed"

    db.commit()
    return created


# ---------------------------------------------------------------------------
# Migración de deuda a TC
# ---------------------------------------------------------------------------

def migrate_debt_to_tc(db: Session, req: MigrateDebtRequest) -> dict:
    """Migra una deuda existente a una tarjeta de crédito.

    migration_type:
    - 'normal'    : crea un cargo único en la TC por el saldo pendiente y
                    cierra la deuda.
    - 'visacuota' : crea un plan de visacuotas manteniendo las cuotas restantes
                    y cierra la deuda.
    """
    user = _get_user_or_raise(db, req.telegram_user_id)

    debt = db.scalar(
        select(Debt).where(
            Debt.id == req.debt_id,
            Debt.user_id == user.id,
        )
    )
    if not debt:
        raise ValueError("Deuda no encontrada.")
    if debt.status != "active":
        raise ValueError("La deuda no está activa.")

    cc_account = db.scalar(
        select(Account).where(
            Account.id == req.credit_card_account_id,
            Account.user_id == user.id,
            Account.account_type == "credit_card",
            Account.is_active == True,
        )
    )
    if not cc_account:
        raise ValueError("Tarjeta de crédito no encontrada o inactiva.")

    pending_installments = max(debt.total_installments - debt.paid_installments, 0)
    remaining_amount = round(pending_installments * float(debt.installment_amount), 2)

    if pending_installments == 0:
        raise ValueError("La deuda no tiene cuotas pendientes.")

    egr_category = _find_egr_category(db, user.id)

    if req.migration_type == "normal":
        # Cargo único en la TC por el saldo restante
        movement = Movement(
            user_id=user.id,
            movement_type="EGR",
            movement_date=date.today(),
            amount=remaining_amount,
            destination_amount=None,
            note=f"Migración de deuda: {debt.name}",
            source_account_id=None,
            target_account_id=None,
            category_id=egr_category.id if egr_category else None,
            payment_method="credit_card",
            transfer_account_id=None,
            loan_person_id=None,
            credit_card_account_id=cc_account.id,
        )
        db.add(movement)

        # Cerrar la deuda marcando todas las cuotas como pagadas
        debt.paid_installments = debt.total_installments
        debt.status = "paid"
        db.commit()

        return {
            "ok": True,
            "message": f"Deuda migrada como cargo único de Q{remaining_amount:,.2f} a {cc_account.name}.",
            "remaining_amount": remaining_amount,
            "pending_installments": pending_installments,
        }

    elif req.migration_type == "visacuota":
        if not req.first_charge_date:
            raise ValueError("first_charge_date es requerido para migración tipo visacuota.")

        first_charge_date = _parse_date(req.first_charge_date)

        plan = CreditCardInstallmentPlan(
            user_id=user.id,
            credit_card_account_id=cc_account.id,
            name=debt.name,
            total_amount=remaining_amount,
            total_installments=pending_installments,
            monthly_amount=float(debt.installment_amount),
            purchase_date=date.today(),
            first_charge_date=first_charge_date,
            status="active",
            note=f"Migrado desde deuda con {debt.creditor}",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)

        # Cerrar la deuda
        debt.paid_installments = debt.total_installments
        debt.status = "paid"
        db.commit()
        db.refresh(plan)

        return {
            "ok": True,
            "message": (
                f"Deuda migrada como plan de {pending_installments} cuotas de "
                f"Q{float(debt.installment_amount):,.2f} en {cc_account.name}."
            ),
            "remaining_amount": remaining_amount,
            "pending_installments": pending_installments,
        }

    else:
        raise ValueError("migration_type inválido. Use 'normal' o 'visacuota'.")
