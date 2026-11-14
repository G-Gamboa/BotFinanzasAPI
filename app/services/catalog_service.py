from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User
from app.services.finance_context import FinanceContext, resolve_context


LIQUID_TYPES = {"cash", "bank"}
INVESTMENT_TYPES = {"investment"}


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def build_catalogs(db: Session, telegram_user_id: int, settings: Settings, ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    user = ctx.user

    is_admin = user.telegram_user_id in settings.admin_telegram_ids
    can_use_loans = bool(user.can_use_loans) or is_admin
    can_use_private_palettes = user.telegram_user_id in settings.private_palette_user_ids

    accounts = sorted((a for a in ctx.accounts if a.is_active), key=lambda a: (a.sort_order, a.name))

    categories = sorted((c for c in ctx.categories if c.is_active), key=lambda c: (c.kind, c.name))

    loan_people = []
    if can_use_loans:
        loan_people = sorted((p for p in ctx.loan_people if p.is_active), key=lambda p: p.name)

    liquid_accounts = []
    investment_accounts = []
    credit_card_accounts = []
    ahorro_account = None
    prestamos_account = None

    for a in accounts:
        item = {
            "id": int(a.id),
            "name": a.name,
            "account_type": a.account_type,
            "currency": a.currency,
        }

        if a.name.lower() == "ahorro":
            ahorro_account = item
        elif a.name.lower() == "prestamos":
            prestamos_account = item
        elif a.account_type in LIQUID_TYPES:
            liquid_accounts.append(item)
        elif a.account_type in INVESTMENT_TYPES:
            investment_accounts.append(item)
        elif a.account_type == "credit_card":
            item["tc_type"] = a.tc_type or "GTQ"
            item["tc_exchange_rate"] = float(a.tc_exchange_rate) if a.tc_exchange_rate is not None else None
            item["billing_close_day"] = a.billing_close_day
            item["payment_due_day"] = a.payment_due_day
            credit_card_accounts.append(item)

    ing_categories = []
    egr_categories = []

    for c in categories:
        item = {
            "id": int(c.id),
            "name": c.name,
            "kind": c.kind,
        }

        if c.kind == "ING":
            ing_categories.append(item)
        elif c.kind == "EGR":
            egr_categories.append(item)

    # Alfabético, "Otros" siempre al final de cada grupo
    def _sort_cats(lst):
        return sorted(lst, key=lambda c: (c["name"].lower() == "otros", c["name"].lower()))

    ing_categories = _sort_cats(ing_categories)
    egr_categories = _sort_cats(egr_categories)

    loan_people_items = [
        {
            "id": int(p.id),
            "name": p.name,
        }
        for p in loan_people
    ]

    return {
        "user": {
            "telegram_user_id": int(user.telegram_user_id),
            "can_use_loans": can_use_loans,
            "can_use_private_palettes": can_use_private_palettes,
            "is_admin": is_admin,
            "theme_key": user.theme_key,
        },
        "accounts": {
            "liquid": liquid_accounts,
            "investment": investment_accounts,
            "credit_cards": credit_card_accounts,
            "ahorro": ahorro_account,
            "prestamos": prestamos_account,
        },
        "categories": {
            "ing": ing_categories,
            "egr": egr_categories,
        },
        "loan_people": loan_people_items,
    }