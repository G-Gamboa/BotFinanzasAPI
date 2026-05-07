from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    User, Movement, Account, Category,
    LoanPerson, Loan, LoanPayment, DebtPayment, Debt,
)


VALID_MOVEMENT_TYPES = {"ING", "EGR", "MOV"}


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def parse_optional_date(value: str | None):
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Las fechas deben usar formato YYYY-MM-DD.")


def detect_subtype(
    movement: Movement,
    source_name: str | None,
    target_name: str | None,
    category_name: str | None,
    loan_person_name: str | None,
) -> str:
    if movement.movement_type == "ING":
        return "INGRESO"
    if movement.movement_type == "EGR":
        return "EGRESO"
    if movement.movement_type != "MOV":
        return "OTRO"

    if source_name == "Ahorro" or target_name == "Ahorro":
        return "AHORRO"
    if loan_person_name or source_name == "Prestamos" or target_name == "Prestamos":
        return "PRESTAMO"

    investment_names = {"binance", "hapi", "ugly", "osmo"}
    if (source_name or "").lower() in investment_names or (target_name or "").lower() in investment_names:
        return "INVERSION"

    return "NORMAL"


def build_history(
    db: Session,
    telegram_user_id: int,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    note: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    parsed_date_from = parse_optional_date(date_from)
    parsed_date_to = parse_optional_date(date_to)

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        raise ValueError("date_from no puede ser mayor que date_to.")

    if movement_type and movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("movement_type debe ser ING, EGR o MOV.")

    # ── Lookup maps ─────────────────────────────────────────────────────────
    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    categories = db.scalars(select(Category).where(Category.user_id == user.id)).all()
    loan_people = db.scalars(select(LoanPerson).where(LoanPerson.user_id == user.id)).all()
    loans_all = db.scalars(select(Loan).where(Loan.user_id == user.id)).all()
    debts_all = db.scalars(select(Debt).where(Debt.user_id == user.id)).all()

    account_by_id = {a.id: a.name for a in accounts}
    category_by_id = {c.id: c.name for c in categories}
    loan_person_by_id = {p.id: p.name for p in loan_people}
    loan_by_id = {l.id: l for l in loans_all}
    debt_by_id = {d.id: d for d in debts_all}

    all_items: list[dict] = []

    # ── 1. Movements ─────────────────────────────────────────────────────────
    include_movements = not movement_type or movement_type in ("ING", "EGR", "MOV")
    if include_movements:
        mov_filters = [
            Movement.user_id == user.id,
            Movement.is_void == False,
        ]
        if parsed_date_from:
            mov_filters.append(Movement.movement_date >= parsed_date_from)
        if parsed_date_to:
            mov_filters.append(Movement.movement_date <= parsed_date_to)
        if movement_type:
            mov_filters.append(Movement.movement_type == movement_type)
        if note and note.strip():
            mov_filters.append(Movement.note.ilike(f"%{note.strip()}%"))

        movements = db.scalars(select(Movement).where(*mov_filters)).all()

        for m in movements:
            source_name = account_by_id.get(m.source_account_id)
            target_name = account_by_id.get(m.target_account_id)
            transfer_name = account_by_id.get(m.transfer_account_id)
            category_name = category_by_id.get(m.category_id)
            loan_person_name = loan_person_by_id.get(m.loan_person_id)

            subtype = detect_subtype(
                movement=m,
                source_name=source_name,
                target_name=target_name,
                category_name=category_name,
                loan_person_name=loan_person_name,
            )

            all_items.append({
                "id": int(m.id),
                "_sort_date": m.movement_date,
                "movement_date": m.movement_date.isoformat(),
                "movement_type": m.movement_type,
                "subtype": subtype,
                "amount": round(float(m.amount), 2),
                "destination_amount": round(float(m.destination_amount), 2) if m.destination_amount is not None else None,
                "source_account": source_name,
                "target_account": target_name,
                "transfer_account": transfer_name,
                "category_name": category_name,
                "loan_person_name": loan_person_name,
                "debt_name": None,
                "payment_method": m.payment_method,
                "note": m.note,
                "is_void": bool(m.is_void),
                "record_type": "movement",
            })

    # ── 2. LoanPayments (cobros de préstamos → ING) ──────────────────────────
    include_loan_payments = not movement_type or movement_type == "ING"
    if include_loan_payments:
        lp_filters = [
            LoanPayment.user_id == user.id,
            LoanPayment.is_void == False,
        ]
        if parsed_date_from:
            lp_filters.append(LoanPayment.payment_date >= parsed_date_from)
        if parsed_date_to:
            lp_filters.append(LoanPayment.payment_date <= parsed_date_to)
        if note and note.strip():
            lp_filters.append(LoanPayment.note.ilike(f"%{note.strip()}%"))

        loan_payments = db.scalars(select(LoanPayment).where(*lp_filters)).all()

        for lp in loan_payments:
            loan = loan_by_id.get(lp.loan_id)
            person_name = loan_person_by_id.get(loan.loan_person_id) if loan else None
            account_name = account_by_id.get(lp.account_id)

            all_items.append({
                "id": int(lp.id),
                "_sort_date": lp.payment_date,
                "movement_date": lp.payment_date.isoformat(),
                "movement_type": "ING",
                "subtype": "COBRO",
                "amount": round(float(lp.amount), 2),
                "destination_amount": None,
                "source_account": None,
                "target_account": account_name,
                "transfer_account": None,
                "category_name": None,
                "loan_person_name": person_name,
                "debt_name": None,
                "payment_method": None,
                "note": lp.note,
                "is_void": bool(lp.is_void),
                "record_type": "loan_payment",
            })

    # ── 3. DebtPayments (pagos de deuda → EGR) ───────────────────────────────
    include_debt_payments = not movement_type or movement_type == "EGR"
    if include_debt_payments:
        dp_filters = [
            DebtPayment.user_id == user.id,
            DebtPayment.is_void == False,
        ]
        if parsed_date_from:
            dp_filters.append(DebtPayment.payment_date >= parsed_date_from)
        if parsed_date_to:
            dp_filters.append(DebtPayment.payment_date <= parsed_date_to)
        if note and note.strip():
            dp_filters.append(DebtPayment.note.ilike(f"%{note.strip()}%"))

        debt_payments = db.scalars(select(DebtPayment).where(*dp_filters)).all()

        for dp in debt_payments:
            debt = debt_by_id.get(dp.debt_id)
            account_name = account_by_id.get(dp.account_id)
            debt_name = debt.name if debt else None

            all_items.append({
                "id": int(dp.id),
                "_sort_date": dp.payment_date,
                "movement_date": dp.payment_date.isoformat(),
                "movement_type": "EGR",
                "subtype": "PAGO_DEUDA",
                "amount": round(float(dp.amount), 2),
                "destination_amount": None,
                "source_account": account_name,
                "target_account": None,
                "transfer_account": None,
                "category_name": None,
                "loan_person_name": None,
                "debt_name": debt_name,
                "payment_method": None,
                "note": dp.note,
                "is_void": bool(dp.is_void),
                "record_type": "debt_payment",
            })

    # ── Sort by date desc, then id desc, paginate ────────────────────────────
    all_items.sort(key=lambda x: (x["_sort_date"], x["id"]), reverse=True)

    total_count = len(all_items)
    paged = all_items[offset: offset + limit]

    # Strip internal sort key before returning
    for item in paged:
        item.pop("_sort_date", None)

    return {
        "items": paged,
        "total": len(paged),
        "total_count": total_count,
    }


# ── Void helpers ─────────────────────────────────────────────────────────────

def void_loan_payment(db: Session, telegram_user_id: int, loan_payment_id: int, reason: str | None) -> LoanPayment:
    user = get_user_or_raise(db, telegram_user_id)
    lp = db.scalar(select(LoanPayment).where(
        LoanPayment.id == loan_payment_id,
        LoanPayment.user_id == user.id,
    ))
    if not lp:
        raise ValueError("Cobro no encontrado.")
    if lp.is_void:
        raise ValueError("El cobro ya está anulado.")

    lp.is_void = True
    lp.void_reason = reason
    lp.voided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lp)
    return lp


def void_debt_payment(db: Session, telegram_user_id: int, debt_payment_id: int, reason: str | None) -> DebtPayment:
    user = get_user_or_raise(db, telegram_user_id)
    dp = db.scalar(select(DebtPayment).where(
        DebtPayment.id == debt_payment_id,
        DebtPayment.user_id == user.id,
    ))
    if not dp:
        raise ValueError("Pago de deuda no encontrado.")
    if dp.is_void:
        raise ValueError("El pago ya está anulado.")

    dp.is_void = True
    dp.void_reason = reason
    dp.voided_at = datetime.now(timezone.utc)

    # Revert the installment counter on the parent debt
    debt = db.scalar(select(Debt).where(Debt.id == dp.debt_id, Debt.user_id == user.id))
    if debt and debt.paid_installments > 0:
        debt.paid_installments -= 1
        debt.status = "paid" if debt.paid_installments >= debt.total_installments else "active"

    db.commit()
    db.refresh(dp)
    return dp
