"""Pago de contado de una tarjeta ajustado a mano.

A veces el banco no procesa un cargo antes del corte y el contado que pide es
menor (o mayor) que el calculado con lo registrado. El ajuste solo cambia lo
que urge pagar en ese corte; el saldo total de la tarjeta no cambia, y lo que
quedó fuera entra solo en el corte siguiente.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, CardStatementOverride, User
from app.services.finance_db_service import _last_close_date, today_gt


def _card(db: Session, telegram_user_id: int, card_id: int) -> tuple[User, Account]:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    card = db.scalar(select(Account).where(Account.id == card_id, Account.user_id == user.id))
    if not card or card.account_type != "credit_card":
        raise ValueError("Tarjeta no encontrada.")
    if not card.billing_close_day:
        raise ValueError("La tarjeta no tiene día de corte configurado.")
    return user, card


def set_statement(db: Session, telegram_user_id: int, card_id: int,
                  amount_q: float | None, amount_usd: float | None) -> CardStatementOverride:
    user, card = _card(db, telegram_user_id, card_id)
    tc_type = card.tc_type or "GTQ"
    if tc_type == "GTQ":
        if amount_q is None:
            raise ValueError("Escribe el pago de contado en quetzales.")
        amount_usd = None
    elif tc_type == "USD":
        if amount_usd is None:
            raise ValueError("Escribe el pago de contado en dólares.")
        amount_q = None
    elif amount_q is None and amount_usd is None:
        raise ValueError("Escribe el pago de contado en quetzales, en dólares o en ambos.")
    for value in (amount_q, amount_usd):
        if value is not None and value < 0:
            raise ValueError("El pago de contado no puede ser negativo.")

    close = _last_close_date(today_gt(), card.billing_close_day)
    row = db.scalar(select(CardStatementOverride).where(
        CardStatementOverride.credit_card_account_id == card.id,
        CardStatementOverride.close_date == close,
    ))
    if row is None:
        row = CardStatementOverride(user_id=user.id, credit_card_account_id=card.id, close_date=close,
                                    created_at=datetime.now(timezone.utc))
        db.add(row)
    row.amount_q = round(amount_q, 2) if amount_q is not None else None
    row.amount_usd = round(amount_usd, 2) if amount_usd is not None else None
    db.commit()
    db.refresh(row)
    return row


def clear_statement(db: Session, telegram_user_id: int, card_id: int) -> None:
    _, card = _card(db, telegram_user_id, card_id)
    close = _last_close_date(today_gt(), card.billing_close_day)
    row = db.scalar(select(CardStatementOverride).where(
        CardStatementOverride.credit_card_account_id == card.id,
        CardStatementOverride.close_date == close,
    ))
    if row is not None:
        db.delete(row)
        db.commit()
