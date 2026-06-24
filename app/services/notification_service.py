import calendar
import json
import logging
import urllib.request
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.services.finance_db_service import build_cc_balances, today_gt

logger = logging.getLogger(__name__)


def _effective_day(d: date, configured_day: int) -> int:
    """Retorna el día real del mes para `configured_day`, clampeado al último día del mes.

    Ej: configured_day=31 en junio (30 días) → retorna 30.
    """
    last = calendar.monthrange(d.year, d.month)[1]
    return min(configured_day, last)


def _fmt_q(amount: float) -> str:
    return f"Q{amount:,.2f}"


def _telegram_send(token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def run_daily_tc_notifications(db: Session) -> dict:
    """Recorre todos los usuarios activos y envía alertas de TC por Telegram.

    Alertas enviadas:
    - Día de corte hoy → saldo que cerró el ciclo
    - 5 días antes del pago → saldo pendiente del ciclo
    - 1 día antes del pago → recordatorio final
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    today = today_gt()
    in_5 = today + timedelta(days=5)
    in_1 = today + timedelta(days=1)

    users = db.scalars(select(User).where(User.is_active == True)).all()

    sent = 0
    skipped = 0
    errors = 0

    for user in users:
        try:
            tc_items = build_cc_balances(db, user.telegram_user_id)
        except Exception:
            skipped += 1
            continue

        for tc in tc_items:
            close_day = tc.get("billing_close_day")
            pay_day   = tc.get("payment_due_day")
            name      = tc.get("name", "TC")
            balance_at_close = tc.get("balance_at_close_gtq") or 0.0
            pending          = tc.get("pending_to_pay_gtq")   or 0.0
            balance_total    = tc.get("balance_gtq")          or 0.0

            messages = []

            # ── Día de corte ──────────────────────────────────────────────
            if close_day and today.day == _effective_day(today, close_day) and balance_total > 0:
                messages.append(
                    f"✂️ *Hoy es fecha de corte* — {name}\n"
                    f"Saldo del ciclo: *{_fmt_q(balance_at_close or balance_total)}*"
                )

            # ── 5 días antes del pago ─────────────────────────────────────
            if pay_day and in_5.day == _effective_day(in_5, pay_day) and pending > 0:
                messages.append(
                    f"📅 *Quedan 5 días para pagar* — {name}\n"
                    f"Saldo a corte pendiente: *{_fmt_q(pending)}*"
                )

            # ── 1 día antes del pago ──────────────────────────────────────
            if pay_day and in_1.day == _effective_day(in_1, pay_day) and pending > 0:
                messages.append(
                    f"⚠️ *Mañana vence el pago* — {name}\n"
                    f"Saldo pendiente: *{_fmt_q(pending)}*"
                )

            for msg in messages:
                try:
                    _telegram_send(token, user.telegram_user_id, msg)
                    sent += 1
                    logger.info(
                        "Notificación TC enviada: user=%s tc=%s",
                        user.telegram_user_id, name,
                    )
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "Error enviando notificación TC: user=%s tc=%s error=%s",
                        user.telegram_user_id, name, exc,
                    )

    return {"sent": sent, "skipped": skipped, "errors": errors, "date": today.isoformat()}
