"""Recordatorios diarios del calendario por Telegram.

Un solo mensaje por usuario y por día: lo de hoy, lo atrasado sin confirmar,
el aviso de saldo en negativo y, el día 1, el cierre del mes anterior.
"""
import json
import logging
import urllib.request
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Debt, ScheduledItem, User
from app.services.calendar_service import (
    LATE_WINDOW_DAYS,
    _cash_rows,
    _Lookups,
    _load_scheduled,
    build_month_close,
    build_projection,
    month_bounds,
)
from app.services.finance_context import FinanceContext
from app.services.finance_db_service import _add_months, build_saldos_map, today_gt

logger = logging.getLogger(__name__)

LATE_REMINDER_DAYS = 7
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
KIND_LABEL = {
    "ingreso": "Ingreso", "pago": "Pago", "abono": "Abono a tarjeta",
    "cargo_tc": "Cargo a tarjeta", "recordatorio": "Recordatorio",
}
LIQUID_TYPES = {"cash", "bank"}


def _q(amount: float) -> str:
    return f"Q{amount:,.2f}"


def _short(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]}"


def _line(row: dict, with_date: bool = False) -> str:
    amount = f" · {_q(row['amount_gtq'])}" if row["amount_gtq"] is not None else ""
    when = f" (era el {_short(date.fromisoformat(row['date']))})" if with_date else ""
    return f"- {KIND_LABEL.get(row['kind'], row['kind'])}: {row['concept']}{amount}{when}"


def build_daily_reminder(db: Session, telegram_user_id: int, today: date | None = None) -> str | None:
    """Texto del recordatorio de hoy, o None si no hay nada que avisar."""
    today = today or today_gt()
    ctx = FinanceContext(db, telegram_user_id)
    items, occ_by_key = _load_scheduled(db, ctx.user.id)
    look = _Lookups(ctx)

    month_end = month_bounds(today.year, today.month)[1]
    rows = _cash_rows(ctx, items, occ_by_key, look, today - timedelta(days=LATE_WINDOW_DAYS), month_end, today)
    pending = [r for r in rows if not r["done"] and (r["source"] == "scheduled" or r["action"])]

    iso_today = today.isoformat()
    late_from = (today - timedelta(days=LATE_REMINDER_DAYS)).isoformat()
    due_today = [r for r in pending if r["date"] == iso_today]
    late = [
        r for r in pending
        if late_from <= r["date"] < iso_today and r["kind"] in ("ingreso", "pago", "abono")
    ]

    parts: list[str] = []
    if due_today:
        parts.append(f"Hoy, {DIAS[today.weekday()]} {_short(today)}:\n" + "\n".join(_line(r) for r in due_today))
    if late:
        parts.append("Sin confirmar de días anteriores:\n" + "\n".join(_line(r, with_date=True) for r in late))

    if due_today or late:
        account_types = {a.name: a.account_type for a in ctx.accounts}
        saldos = build_saldos_map(db, telegram_user_id, ctx)
        cash_now = sum(v for k, v in saldos.items() if account_types.get(k) in LIQUID_TYPES)
        projection = build_projection(cash_now, rows, today, month_end)
        if projection and projection["first_negative"]:
            negative_day = date.fromisoformat(projection["first_negative"])
            lowest = projection["lowest"]["balance"]
            parts.append(
                f"Ojo: con lo planeado, tu saldo quedaría en negativo el {_short(negative_day)} "
                f"(hasta {_q(lowest)})."
            )

    if today.day == 1:
        prev = _add_months(today, -1)
        close = build_month_close(db, ctx, prev.year, prev.month, today, items, occ_by_key, look)
        if close["ingresos"] or close["egresos"] or close["unconfirmed"]:
            lines = [
                f"Cierre de {MESES[prev.month - 1]}:",
                f"- Entró: {_q(close['ingresos'])}",
                f"- Salió: {_q(close['egresos'])}",
                f"- Balance: {_q(close['balance'])}",
                f"- Ahorro del mes: {_q(close['ahorro'])}",
            ]
            if close["unconfirmed"]:
                lines.append(f"- Quedaron {len(close['unconfirmed'])} sin confirmar")
            parts.append("\n".join(lines))

    if not parts:
        return None
    parts.append("Confírmalos en la pestaña Calendario.")
    return "\n\n".join(parts)


def _send_plain(token: str, chat_id: int, text: str) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def run_daily_calendar_notifications(db: Session) -> dict:
    """Envía el recordatorio del día a cada usuario activo que use el calendario o tenga deudas."""
    token = get_settings().telegram_bot_token
    today = today_gt()

    user_ids = set(db.scalars(select(ScheduledItem.user_id).where(ScheduledItem.is_active == True)).all())
    user_ids |= set(db.scalars(select(Debt.user_id).where(Debt.status == "active")).all())
    if not user_ids:
        return {"sent": 0, "errors": 0}

    users = db.scalars(select(User).where(User.id.in_(user_ids), User.is_active == True)).all()
    sent = 0
    errors = 0
    for user in users:
        try:
            text = build_daily_reminder(db, user.telegram_user_id, today)
            if not text:
                continue
            _send_plain(token, user.telegram_user_id, text)
            sent += 1
        except Exception as exc:
            errors += 1
            logger.warning("Error en recordatorio de calendario: user=%s error=%s", user.telegram_user_id, exc)
    return {"sent": sent, "errors": errors}
