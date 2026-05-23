"""Subscription helpers — expiry logic and renewal.

Accounts in settings.admin_telegram_ids are permanently exempt:
  - subscription_active()  → always True
  - extend_subscription()  → no-op (keeps NULL expiry)
  - process_expirations()  → skipped entirely (query excludes them)
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User

SUBSCRIPTION_DAYS = 30
REMINDER_DAYS_BEFORE = 3


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_exempt(user: User) -> bool:
    """Return True if this user is permanently exempt from subscription checks.

    Exempt = ID is listed in PRIVATE_PALETTE_USER_IDS env var.
    Exempt users always have access, are never billed and never deactivated.
    """
    settings = get_settings()
    return int(user.telegram_user_id) in settings.private_palette_user_ids


def subscription_active(user: User) -> bool:
    """Return True if the user currently has valid access.

    Priority:
      1. Exempt (admin) → always True
      2. is_active = False → always False
      3. subscription_expires_at IS NULL → True (legacy/grandfathered account)
      4. subscription_expires_at > now → True
    """
    if is_exempt(user):
        return True
    if not user.is_active:
        return False
    if user.subscription_expires_at is None:
        return True  # grandfathered account created before subscriptions
    return user.subscription_expires_at > now_utc()


def days_remaining(user: User) -> int | None:
    """Days until subscription expires.

    Returns None for exempt or legacy (no-expiry) accounts.
    """
    if is_exempt(user) or user.subscription_expires_at is None:
        return None
    delta = user.subscription_expires_at - now_utc()
    return max(0, delta.days)


def extend_subscription(user: User, days: int = SUBSCRIPTION_DAYS) -> None:
    """Extend subscription by `days`.

    No-op for exempt users — their expiry stays NULL permanently.
    Stacks correctly if renewed before the current expiry.
    """
    if is_exempt(user):
        return  # exempt accounts are never touched
    base = max(now_utc(), user.subscription_expires_at or now_utc())
    user.subscription_expires_at = base + timedelta(days=days)


def format_expiry(user: User) -> str:
    if is_exempt(user) or user.subscription_expires_at is None:
        return "Sin vencimiento"
    return user.subscription_expires_at.strftime("%d/%m/%Y")


def process_expirations(db: Session, bot_token: str) -> dict:
    """Deactivate expired subscriptions and send renewal reminders.

    The query already excludes:
      - Users with subscription_expires_at IS NULL (legacy / no-expiry)
      - Inactive users (already deactivated)

    Exempt (admin) IDs are additionally skipped in the loop as a safety net,
    in case someone manually set an expiry date on an admin account.
    """
    from app.services.telegram_bot import send_message  # avoid circular import

    settings = get_settings()
    exempt_ids = set(settings.admin_telegram_ids)

    now = now_utc()
    reminder_threshold = now + timedelta(days=REMINDER_DAYS_BEFORE)

    # Only fetch users who actually have a subscription expiry date set
    users = db.scalars(
        select(User).where(
            User.is_active == True,
            User.subscription_expires_at.is_not(None),
        )
    ).all()

    deactivated = 0
    reminded = 0

    for user in users:
        # Double-safety: never touch exempt accounts even if they somehow got an expiry
        if int(user.telegram_user_id) in exempt_ids:
            continue

        exp = user.subscription_expires_at
        tg_id = int(user.telegram_user_id)
        name = user.first_name or "Usuario"

        if exp <= now:
            user.is_active = False
            deactivated += 1
            try:
                send_message(
                    bot_token,
                    tg_id,
                    (
                        f"⏰ <b>Tu suscripción venció, {name}.</b>\n\n"
                        "Para seguir usando el gestor de finanzas, "
                        "abre el Mini App y renueva tu suscripción mensual."
                    ),
                )
            except Exception:
                pass

        elif exp <= reminder_threshold:
            days_left = max(1, (exp - now).days)
            reminded += 1
            try:
                send_message(
                    bot_token,
                    tg_id,
                    (
                        f"🔔 <b>Tu suscripción vence en "
                        f"{days_left} día{'s' if days_left != 1 else ''}, {name}.</b>\n\n"
                        "Abre el Mini App y toca <b>Renovar suscripción</b> "
                        "para continuar sin interrupciones."
                    ),
                )
            except Exception:
                pass

    db.commit()
    return {"deactivated": deactivated, "reminded": reminded, "checked": len(users)}
