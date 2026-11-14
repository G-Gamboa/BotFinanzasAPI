"""Carga inicial del calendario para la cuenta del administrador.

Se aplica una sola vez: queda marcada en app_seeds, así que reiniciar el
servidor no la repite ni restaura lo que el usuario haya borrado después.
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Account, AppSeed, CalendarNote, Debt, ScheduledItem, ScheduledOccurrence, User,
)

logger = logging.getLogger(__name__)

SEED_KEY = "calendar_seed_v1"
SEED_TELEGRAM_USER_ID = 1282471582

# (tipo, concepto, monto, moneda, inicio, repetición, fin, nota, va_a_la_tarjeta)
_ITEMS = [
    ("ingreso", "Quincena", 3168.16, "GTQ", date(2026, 11, 20), "monthly", None, None, False),
    ("ingreso", "Quincena", 3168.16, "GTQ", date(2026, 12, 5), "monthly", None, None, False),
    ("ingreso", "Ingreso del 15", 135, "GTQ", date(2026, 11, 15), "none", None, None, False),
    ("ingreso", "Extra del mes", 510, "GTQ", date(2026, 12, 2), "monthly", date(2027, 1, 2), "El último es el de enero, por ahora", False),
    ("ingreso", "Reintegro Cemaco.com", 103.9, "GTQ", date(2026, 12, 3), "monthly", date(2027, 2, 3), None, False),
    ("ingreso", "Boa Estudio", 1800, "GTQ", None, "none", None, "Pendiente de depósito", False),
    ("ingreso", "Pago de Puma", 252.09, "GTQ", None, "none", None, "Cuando pague, abónalo a la tarjeta", False),
    ("abono", "Abonar el ingreso del 15", 135, "GTQ", date(2026, 11, 15), "none", None,
     "Si Boa todavía no llega, úsalo como efectivo y súmalo al abono del 5 de diciembre", True),
    ("abono", "Abonar de la quincena", 1500, "GTQ", date(2026, 11, 20), "none", None,
     "De la quincena: aparta Q900 para el 22, Q312.50 para el 24 y Q455.66 de efectivo", True),
    ("abono", "Abonar el extra del mes", 510, "GTQ", date(2026, 12, 2), "none", None, None, True),
    ("abono", "Abonar el reintegro", 103.9, "GTQ", date(2026, 12, 3), "none", None, None, True),
    ("abono", "Resto del pago en quetzales", 2276.1, "GTQ", date(2026, 12, 5), "none", None,
     "Estimado: ajústalo con el contado del corte", True),
    ("abono", "Dólares del corte, comprados con NEXA", 33, "USD", date(2026, 12, 5), "none", None,
     "Estimado; NEXA a 7.7733", True),
    ("abono", "Abonar lo de Boa", 1575, "GTQ", None, "none", None,
     "De los Q1,800; los otros Q225 quedan en efectivo", True),
    ("pago", "Aporte en casa", 500, "GTQ", None, "none", None, "Cada mes desde enero", False),
    ("cargo_tc", "Meta cobra la campaña", 50, "USD", date(2026, 11, 18), "monthly", date(2027, 1, 18),
     "Necesita unos Q390 de línea", True),
    ("cargo_tc", "Luz", None, "GTQ", date(2026, 11, 25), "monthly", date(2027, 2, 25),
     "Con la tarjeta; va al pago del mes siguiente", True),
    ("cargo_tc", "Internet", 160, "GTQ", date(2026, 11, 27), "monthly", date(2027, 2, 27), "Se paga desde Bi", True),
]

# Pagos de deuda del plan original: solo se cargan si el bot no tiene ya una
# deuda activa con esa cuota (en ese caso el calendario la muestra sola).
_DEBT_ITEMS = [
    ("pago", "Pago de deuda", 900, "GTQ", date(2026, 11, 22), "none", None, None, False),
    ("pago", "Pago de deuda", 312.5, "GTQ", date(2026, 11, 24), "monthly", date(2027, 2, 24), "El último es el de febrero", False),
]

_NOTES = [
    "Todo o nada: si no completas el contado en quetzales y en dólares, Bi cobra intereses sobre todo el corte.",
]


def _pick_card(cards: list[Account]) -> Account | None:
    if len(cards) == 1:
        return cards[0]
    for card in cards:
        if "bi" in card.name.lower().split():
            return card
    for card in cards:
        if "bi" in card.name.lower():
            return card
    return None


def seed_admin_calendar(db: Session) -> bool:
    """Devuelve True si aplicó la carga en esta llamada."""
    if db.get(AppSeed, SEED_KEY) is not None:
        return False

    user = db.scalar(select(User).where(User.telegram_user_id == SEED_TELEGRAM_USER_ID))
    if user is None:
        return False

    now = datetime.now(timezone.utc)
    cards = list(db.scalars(select(Account).where(
        Account.user_id == user.id, Account.account_type == "credit_card", Account.is_active == True,
    )).all())
    card = _pick_card(cards)

    debt_amounts = {
        round(float(d.installment_amount), 2)
        for d in db.scalars(select(Debt).where(Debt.user_id == user.id, Debt.status == "active")).all()
    }
    rows = list(_ITEMS) + [r for r in _DEBT_ITEMS if round(float(r[2]), 2) not in debt_amounts]

    # Si la tarjeta no tiene configurados corte y pago, se agregan como recordatorios.
    if card is None or not card.billing_close_day:
        rows.append(("recordatorio", "Corte de la tarjeta Bi", None, "GTQ", date(2026, 11, 13), "monthly", None, None, True))
    if card is None or not card.payment_due_day:
        rows.append(("recordatorio", "Fecha de pago Bi", None, "GTQ", date(2026, 12, 7), "monthly", None,
                     "El contado en quetzales y en dólares tiene que quedar en cero", True))

    for kind, concept, amount, currency, start, recurrence, end, note, uses_card in rows:
        item = ScheduledItem(
            user_id=user.id, kind=kind, concept=concept, amount=amount, currency=currency,
            start_date=start, recurrence=recurrence, end_date=end, note=note,
            credit_card_account_id=card.id if (uses_card and card) else None,
            payment_method="credit_card" if kind == "cargo_tc" else None,
            is_active=True, created_at=now,
        )
        db.add(item)
        if concept == "Luz":
            db.flush()
            db.add(ScheduledOccurrence(
                item_id=item.id, user_id=user.id, due_date=date(2026, 11, 25), status="pending", amount=618,
            ))

    for text in _NOTES:
        db.add(CalendarNote(user_id=user.id, text=text, created_at=now))

    db.add(AppSeed(key=SEED_KEY, applied_at=now))
    db.commit()
    logger.info("Carga inicial del calendario aplicada: %d programados.", len(rows))
    return True
