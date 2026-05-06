from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Debt, Account, DebtPayment


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


def create_debt(
    db: Session,
    telegram_user_id: int,
    name: str,
    creditor: str,
    due_date: str,
    installment_amount: float,
    total_installments: int,
    paid_installments: int,
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
        status="paid" if paid_installments >= total_installments else "active",
    )

    db.add(debt)
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

    db.commit()
    db.refresh(debt)
    return debt