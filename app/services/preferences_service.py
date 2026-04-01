from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, UserSetting


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def get_or_create_user_settings(db: Session, user_id: int) -> UserSetting:
    settings = db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
    if settings:
        return settings

    settings = UserSetting(
        user_id=user_id,
        usd_to_gtq=7.7,
        show_amounts_default=False,
        default_tab="movimientos",
        theme_key=None,
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def get_preferences(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    settings = get_or_create_user_settings(db, user.id)

    default_tab = getattr(settings, "default_tab", "movimientos")
    show_amounts_default = getattr(settings, "show_amounts_default", False)
    usd_to_gtq = float(getattr(settings, "usd_to_gtq", 7.7))
    theme_key = getattr(settings, "theme_key", None)

    if default_tab == "prestamos" and not user.can_use_loans:
        default_tab = "movimientos"

    return {
        "telegram_user_id": int(user.telegram_user_id),
        "show_amounts_default": bool(show_amounts_default),
        "default_tab": default_tab,
        "usd_to_gtq": usd_to_gtq,
        "theme_key": theme_key,
    }


def update_preferences(
    db: Session,
    telegram_user_id: int,
    show_amounts_default: bool,
    default_tab: str,
    usd_to_gtq: float,
    theme_key: str | None,
) -> None:
    user = get_user_or_raise(db, telegram_user_id)
    settings = get_or_create_user_settings(db, user.id)

    if default_tab == "prestamos" and not user.can_use_loans:
        raise ValueError("Este usuario no puede usar la pestaña de préstamos.")

    settings.show_amounts_default = show_amounts_default
    settings.default_tab = default_tab
    settings.usd_to_gtq = usd_to_gtq
    settings.theme_key = theme_key

    db.commit()