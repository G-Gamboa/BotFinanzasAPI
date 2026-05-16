from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User, Account, Category, LoanPerson


LIQUID_TYPES = {"cash", "bank"}
INVESTMENT_TYPES = {"investment"}


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def build_catalogs(db: Session, telegram_user_id: int, settings: Settings) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    is_admin = user.telegram_user_id in settings.admin_telegram_ids
    can_use_loans = bool(user.can_use_loans) or is_admin
    can_use_private_palettes = is_admin

    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.is_active == True)
        .order_by(Account.sort_order, Account.name)
    ).all()

    categories = db.scalars(
        select(Category)
        .where(Category.user_id == user.id, Category.is_active == True)
        .order_by(Category.kind, Category.sort_order, Category.name)
    ).all()

    loan_people = []
    if can_use_loans:
        loan_people = db.scalars(
            select(LoanPerson).where(LoanPerson.user_id == user.id).order_by(LoanPerson.name)
        ).all()

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