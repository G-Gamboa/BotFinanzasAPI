from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Debt, Account, DebtPayment
from app.services.finance_db_service import build_saldos_map


LIQUID_TYPES = {"cash", "bank"}


def parse_iso_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe usar formato YYYY-MM-DD.")


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def advance_due_date(current: object, frequency: str):
    """Return the next due_date based on payment_frequency."""
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "biweekly":
        return current + timedelta(weeks=2)
    if frequency == "monthly":
        return current + relativedelta(months=1)
    return current  # "none" — no change


def create_debt(
    db: Session,
    telegram_user_id: int,
    name: str,
    creditor: str,
    due_date: str,
    installment_amount: float,
    total_installments: int,
    paid_installments: int,
    payment_frequency: str = "monthly",
) -> Debt:
    user = get_user_or_raise(db, telegram_user_id)

    debt = Debt(
        user_id=user.id,
        name=name.strip(),
        creditor=creditor.strip(),
        due_date=parse_iso_date(due_date),
        installment_amount=installment_amount,
        total_installments=total_installments,
        paid_installments=paid_installments,
        payment_frequency=payment_frequency,
        status="paid" if paid_installments >= total_installments else "active",
    )

    db.add(debt)
    db.commit()
    db.refresh(debt)
    return debt


def update_debt(
    db: Session,
    telegram_user_id: int,
    debt_id: int,
    name: str,
    creditor: str,
    due_date: str,
    installment_amount: float,
    total_installments: int,
    payment_frequency: str = "monthly",
) -> Debt:
    user = get_user_or_raise(db, telegram_user_id)
    debt = db.scalar(select(Debt).where(Debt.id == debt_id, Debt.user_id == user.id))
    if not debt:
        raise ValueError("Deuda no encontrada.")

    debt.name = name.strip()
    debt.creditor = creditor.strip()
    debt.due_date = parse_iso_date(due_date)
    debt.installment_amount = installment_amount
    debt.total_installments = total_installments
    debt.payment_frequency = payment_frequency
    debt.status = "paid" if debt.paid_installments >= debt.total_installments else "active"

    db.commit()
    db.refresh(debt)
    return debt


def pay_debt(
    db: Session,
    telegram_user_id: int,
    debt_id: int,
    payment_date: str,
    payment_method: str,
    account_name: str,
    note: str | None = None,
) -> Debt:
    user = get_user_or_raise(db, telegram_user_id)

    debt = db.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.user_id == user.id)
    )
    if not debt:
        raise ValueError("Deuda no encontrada.")

    if debt.paid_installments >= debt.total_installments:
        raise ValueError("La deuda ya está pagada.")

    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    account_by_name = {a.name.lower(): a for a in accounts}

    account = account_by_name.get(account_name.strip().lower())
    if not account:
        raise ValueError("La cuenta no existe.")
    if account.account_type not in LIQUID_TYPES:
        raise ValueError("La cuenta para pagar deuda debe ser líquida.")

    pay_date = parse_iso_date(payment_date)

    # Validate sufficient balance
    saldos = build_saldos_map(db, user.telegram_user_id)
    available = saldos.get(account.name, 0.0)
    needed = float(debt.installment_amount)
    if needed > available:
        raise ValueError(
            f"Saldo insuficiente en {account.name}. "
            f"Disponible: Q {available:,.2f} · Necesario: Q {needed:,.2f}."
        )

    debt_payment = DebtPayment(
        debt_id=debt.id,
        user_id=user.id,
        amount=float(debt.installment_amount),
        payment_date=pay_date,
        account_id=account.id,
        note=note or f"Pago de deuda: {debt.name}",
    )
    db.add(debt_payment)

    debt.paid_installments += 1
    if debt.paid_installments >= debt.total_installments:
        debt.status = "paid"
    else:
        debt.status = "active"
        # Advance next due date only while debt is still active
        debt.due_date = advance_due_date(debt.due_date, debt.payment_frequency)

    db.commit()
    db.refresh(debt)
    return debt