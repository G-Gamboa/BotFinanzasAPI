"""Subscription helpers — expiry logic and renewal."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

SUBSCRIPTION_DAYS = 30
REMINDER_DAYS_BEFORE = 3  # send reminder when N days left


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def subscription_active(user: User) -> bool:
    """Return True if the user's subscription is currently valid.

    NULL subscription_expires_at means no expiry (legacy/admin accounts).
    """
    if not user.is_active:
        return False
    if user.subscription_expires_at is None:
        return True  # legacy account — no expiry enforced
    return user.subscription_expires_at > now_utc()


def days_remaining(user: User) -> int | None:
    """Days until subscription expires. None if no expiry date."""
    if user.subscription_expires_at is None:
        return None
    delta = user.subscription_expires_at - now_utc()
    return max(0, delta.days)


def extend_subscription(user: User, days: int = SUBSCRIPTION_DAYS) -> None:
    """Add `days` to the subscription, starting from today or current expiry
    (whichever is later), so renewals before expiry stack correctly."""
    base = max(now_utc(), user.subscription_expires_at or now_utc())
    user.subscription_expires_at = base + timedelta(days=days)


def format_expiry(user: User) -> str:
    if user.subscription_expires_at is None:
        return "Sin vencimiento"
    local = user.subscription_expires_at  # stored as UTC; display as-is
    return local.strftime("%d/%m/%Y")


def process_expirations(db: Session, bot_token: str) -> dict:
    """Check all active users for upcoming or past expirations.

    - Expired (< now):           deactivate + send deactivation notice
    - Expiring soon (≤ N days):  send renewal reminder (once per day guard not
                                  included here — call from a cron max once/day)

    Returns counts for logging.
    """
    from app.services.telegram_bot import send_message  # avoid circular import

    now = now_utc()
    reminder_threshold = now + timedelta(days=REMINDER_DAYS_BEFORE)

    users = db.scalars(
        select(User).where(
            User.is_active == True,
            User.subscription_expires_at.is_not(None),
        )
    ).all()

    deactivated = 0
    reminded = 0

    for user in users:
        exp = user.subscription_expires_at
        tg_id = int(user.telegram_user_id)
        name = user.first_name or "Usuario"

        if exp <= now:
            # Expired → deactivate
            user.is_active = False
            deactivated += 1
            try:
                send_message(
                    bot_token,
                    tg_id,
                    (
                        f"⏰ <b>Tu suscripción venció, {name}.</b>\n\n"
                        "Para seguir usando el gestor de finanzas, abre el Mini App y renueva tu suscripción mensual."
                    ),
                )
            except Exception:
                pass

        elif exp <= reminder_threshold:
            # Expiring soon → send reminder
            days_left = max(1, (exp - now).days)
            reminded += 1
            try:
                send_message(
                    bot_token,
                    tg_id,
                    (
                        f"🔔 <b>Tu suscripción vence en {days_left} día{'s' if days_left != 1 else ''}, {name}.</b>\n\n"
                        "Abre el Mini App y toca <b>Renovar suscripción</b> para continuar sin interrupciones."
                    ),
                )
            except Exception:
                pass

    db.commit()
    return {"deactivated": deactivated, "reminded": reminded, "checked": len(users)}
