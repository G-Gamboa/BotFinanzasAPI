"""Planes de cobro de préstamos: cuánto y cuándo se espera que cada persona pague.

Un plan se define por persona y concepto, la misma unidad con que se cobran
los préstamos. Lo que falta por cobrar incluye las visacuotas de préstamo que
todavía no se cargan, así el plan se proyecta hasta cubrir todo.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LoanCollectionPlan
from app.schemas.transactions import MovementCreateRequest
from app.services.debt_service import advance_due_date
from app.services.finance_context import FinanceContext, resolve_context
from app.services.finance_db_service import today_gt
from app.services.loans_view_service import normalize_loan_concept
from app.services.transaction_service import create_movement

FREQUENCIES = {"weekly", "biweekly", "monthly"}
MAX_PROJECTED = 120
LIQUID_TYPES = {"cash", "bank"}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe usar formato YYYY-MM-DD.")


def _plans(ctx: FinanceContext) -> list[LoanCollectionPlan]:
    if "collection_plans" not in ctx.memo:
        ctx.memo["collection_plans"] = list(ctx.db.scalars(select(LoanCollectionPlan).where(
            LoanCollectionPlan.user_id == ctx.user.id, LoanCollectionPlan.is_active == True,
        )).all())
    return ctx.memo["collection_plans"]


def _groups(ctx: FinanceContext) -> dict[tuple[int, str], dict]:
    """Por persona y concepto: saldo, visacuotas por cargar, tarjeta y cuota sugerida."""
    if "collection_groups" in ctx.memo:
        return ctx.memo["collection_groups"]

    people = {p.id: p.name for p in ctx.loan_people}
    cards = {a.id: a.name for a in ctx.accounts if a.account_type == "credit_card"}
    groups: dict[tuple[int, str], dict] = {}

    def group(person_id: int, concept: str) -> dict:
        key = (person_id, concept)
        if key not in groups:
            groups[key] = {
                "person_id": person_id, "person": people.get(person_id, "—"), "concept": concept,
                "balance": 0.0, "upcoming": 0.0, "card_id": None, "default_amount": None,
            }
        return groups[key]

    loans = [l for l in ctx.loans if l.loan_type == "lent" and l.status != "cancelled"]
    by_id = {l.id: l for l in loans}
    for loan in loans:
        g = group(loan.loan_person_id, normalize_loan_concept(loan.note))
        g["balance"] += float(loan.principal_amount)
        if loan.source_tc_account_id:
            g["card_id"] = loan.source_tc_account_id
    for payment in ctx.loan_payments:
        loan = by_id.get(payment.loan_id)
        if loan:
            group(loan.loan_person_id, normalize_loan_concept(loan.note))["balance"] -= float(payment.amount)

    # Visacuotas de préstamo: cada cuota aún no cargada se cobrará después
    paid_by_plan = ctx.paid_by_plan
    for plan in ctx.plans:
        if not (plan.is_loan and plan.is_active and plan.status == "active" and plan.loan_person_id):
            continue
        g = group(plan.loan_person_id, normalize_loan_concept(plan.name))
        left = max(plan.total_installments - paid_by_plan.get(plan.id, 0), 0)
        g["upcoming"] += left * float(plan.monthly_amount)
        g["card_id"] = plan.credit_card_account_id
        g["default_amount"] = round(float(plan.monthly_amount), 2)

    for g in groups.values():
        g["balance"] = round(g["balance"], 2)
        g["upcoming"] = round(g["upcoming"], 2)
        g["card_name"] = cards.get(g["card_id"]) if g["card_id"] else None
    ctx.memo["collection_groups"] = groups
    return groups


def _plan_dict(plan: LoanCollectionPlan) -> dict:
    return {
        "id": int(plan.id),
        "installment_amount": round(float(plan.installment_amount), 2),
        "frequency": plan.frequency,
        "next_due_date": plan.next_due_date.isoformat(),
    }


def list_collections(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict:
    """Lo que te deben, por persona y concepto, con su plan de cobro si tiene."""
    ctx = resolve_context(db, telegram_user_id, ctx)
    groups = _groups(ctx)
    plan_by_key = {(p.loan_person_id, p.concept): p for p in _plans(ctx)}

    items = []
    for key, g in groups.items():
        if g["balance"] <= 0.005 and g["upcoming"] <= 0.005:
            continue
        plan = plan_by_key.get(key)
        items.append({
            "person_id": g["person_id"],
            "person": g["person"],
            "concept": g["concept"],
            "balance": g["balance"],
            "upcoming": g["upcoming"],
            "is_tc": g["card_id"] is not None,
            "card_name": g["card_name"],
            "is_visacuota": g["default_amount"] is not None,
            "default_amount": g["default_amount"],
            "plan": _plan_dict(plan) if plan else None,
        })
    items.sort(key=lambda i: (i["person"].lower(), i["concept"] != "General", i["concept"].lower()))
    return {"items": items}


def _row(key: str, due: date, plan: LoanCollectionPlan, g: dict, amount: float, today: date,
         *, done: bool = False, action: str | None = None, note: str | None = None,
         record_id: int | None = None) -> dict:
    concept = g["concept"]
    return {
        "key": key,
        "source": "collection",
        "item_id": None,
        "date": due.isoformat(),
        "kind": "cobro",
        "concept": f"Cobro a {g['person']}" + ("" if concept == "General" else f" · {concept}"),
        "amount": round(amount, 2),
        "currency": "GTQ",
        "amount_gtq": round(amount, 2),
        "note": note,
        "done": done,
        "late": bool(due < today and not done and action),
        "action": action,
        "recurring": False,
        "recurrence": "none",
        "needs_amount": False,
        "account_name": None,
        "category_name": None,
        "payment_method": None,
        "credit_card_account_id": g["card_id"],
        "credit_card_name": g["card_name"],
        "record_type": "loan_payment" if done else None,
        "record_id": record_id,
        "plan_id": int(plan.id),
        "person": g["person"],
        "loan_concept": concept,
        "balance": g["balance"],
    }


def collection_rows(ctx: FinanceContext, start: date, end: date, today: date) -> list[dict]:
    """Cobros esperados y cobros hechos de los conceptos con plan, dentro de [start, end]."""
    groups = _groups(ctx)
    rows: list[dict] = []
    for plan in _plans(ctx):
        g = groups.get((plan.loan_person_id, plan.concept))
        if g is None:
            continue

        pending = round(g["balance"] + g["upcoming"], 2)
        installment = float(plan.installment_amount)
        current = plan.next_due_date
        n = 0
        while pending > 0.005 and n < MAX_PROJECTED and current <= end:
            amount = min(installment, pending)
            pending = round(pending - amount, 2)
            if current >= start:
                note = "Último cobro" if pending <= 0.005 else f"Quedan Q{pending:,.2f} después de este"
                if g["card_id"]:
                    note += f" · se abona a {g['card_name']}"
                rows.append(_row(
                    f"c:{plan.id}:{current.isoformat()}", current, plan, g, amount, today,
                    action="confirm" if n == 0 else None, note=note,
                ))
            current = advance_due_date(current, plan.frequency)
            n += 1

    # Cobros ya registrados de esos conceptos
    planned = {(p.loan_person_id, p.concept): p for p in _plans(ctx)}
    loans = {l.id: l for l in ctx.loans}
    for payment in ctx.loan_payments:
        if not (start <= payment.payment_date <= end):
            continue
        loan = loans.get(payment.loan_id)
        if loan is None:
            continue
        key = (loan.loan_person_id, normalize_loan_concept(loan.note))
        plan = planned.get(key)
        if plan is None:
            continue
        rows.append(_row(
            f"lp:{payment.id}", payment.payment_date, plan, groups[key], float(payment.amount), today,
            done=True, record_id=int(payment.id),
        ))
    return rows


# ── Alta, edición y baja de planes ───────────────────────────────────────────

def save_plan(db: Session, telegram_user_id: int, loan_person_id: int, concept: str | None,
              installment_amount: float, frequency: str, next_due_date: str) -> LoanCollectionPlan:
    ctx = FinanceContext(db, telegram_user_id)
    if frequency not in FREQUENCIES:
        raise ValueError("Frecuencia inválida.")
    due = _parse_date(next_due_date)
    if due is None:
        raise ValueError("Falta la fecha del próximo cobro.")
    if not any(p.id == loan_person_id for p in ctx.loan_people):
        raise ValueError("Persona no encontrada.")
    concept = normalize_loan_concept(concept)

    plan = db.scalar(select(LoanCollectionPlan).where(
        LoanCollectionPlan.user_id == ctx.user.id,
        LoanCollectionPlan.loan_person_id == loan_person_id,
        LoanCollectionPlan.concept == concept,
        LoanCollectionPlan.is_active == True,
    ))
    if plan is None:
        plan = LoanCollectionPlan(
            user_id=ctx.user.id, loan_person_id=loan_person_id, concept=concept,
            is_active=True, created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
    plan.installment_amount = installment_amount
    plan.frequency = frequency
    plan.next_due_date = due
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, telegram_user_id: int, plan_id: int) -> None:
    ctx = FinanceContext(db, telegram_user_id)
    plan = db.scalar(select(LoanCollectionPlan).where(
        LoanCollectionPlan.id == plan_id, LoanCollectionPlan.user_id == ctx.user.id,
        LoanCollectionPlan.is_active == True,
    ))
    if not plan:
        raise ValueError("Plan de cobro no encontrado.")
    plan.is_active = False
    db.commit()


def confirm_collection(db: Session, telegram_user_id: int, plan_id: int, payment_date: str,
                       amount: float | None, account_name: str | None, create_record: bool) -> dict:
    """Registra el cobro (o solo lo marca) y mueve el plan al siguiente periodo."""
    ctx = FinanceContext(db, telegram_user_id)
    plan = next((p for p in _plans(ctx) if p.id == plan_id), None)
    if plan is None:
        raise ValueError("Plan de cobro no encontrado.")
    paid_on = _parse_date(payment_date)
    if paid_on is None:
        raise ValueError("Falta la fecha.")
    if paid_on > today_gt() + timedelta(days=7):
        raise ValueError("La fecha no puede ser más de 7 días en el futuro.")

    g = _groups(ctx).get((plan.loan_person_id, plan.concept))
    person = next((p for p in ctx.loan_people if p.id == plan.loan_person_id), None)
    record_id = None

    if create_record:
        if amount is None or amount <= 0:
            raise ValueError("Escribe el monto.")
        if g is None or g["balance"] <= 0.005:
            raise ValueError("Todavía no hay saldo cargado para cobrar en este concepto.")
        is_tc = g["card_id"] is not None
        if not is_tc:
            account = next((a for a in ctx.accounts if a.name.lower() == (account_name or "").strip().lower()), None)
            if account is None or account.account_type not in LIQUID_TYPES:
                raise ValueError("Elige la cuenta donde entra el cobro.")
        payment = create_movement(db, MovementCreateRequest(
            telegram_user_id=telegram_user_id, movement_type="MOV", movement_date=payment_date,
            amount=amount, note=None if plan.concept == "General" else plan.concept,
            mov_subtype="PRESTAMO", mov_direction="COBRAR",
            loan_person_name=person.name if person else "",
            target_account_name=None if is_tc else account_name,
        ))
        record_id = int(payment.id)

    plan = db.get(LoanCollectionPlan, plan_id)
    plan.next_due_date = advance_due_date(plan.next_due_date, plan.frequency)
    db.commit()
    return {"record_type": "loan_payment" if record_id else None, "record_id": record_id}
